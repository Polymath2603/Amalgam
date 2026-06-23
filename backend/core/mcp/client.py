"""
MCP Client — connects to MCP servers via stdio or SSE transport, discovers tools, and calls them.
Supports both local (stdio) and remote (SSE/HTTP) MCP servers.
Integrates hook system, permission system, and tool analytics.
"""
import json
import time
import asyncio
import logging
import os
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Dict, List, Optional
from contextlib import AsyncExitStack
from urllib.parse import urlparse

import httpx

# Graceful degradation when mcp package is not installed (e.g. Android/aarch64
# where pydantic-core can't build, or environments that don't need MCP tools).
_MCP_AVAILABLE = True
try:
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.session import ClientSession
except ModuleNotFoundError:
    _MCP_AVAILABLE = False
    ClientSession = object  # placeholder for type annotations

from backend.core.agent.permissions import ToolPermissions, PermissionLevel, PermissionGate
from backend.core.agent.hooks import ToolHooks
from backend.core.agent.analytics import ToolAnalytics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured result type for tool calls
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    """Structured result from a tool call, replacing stringly-typed error prefixes."""
    success: bool
    content: str = ""
    error: Optional[str] = None
    tool_name: str = ""

    def to_str(self) -> str:
        """Return a string representation for backward compatibility."""
        if not self.success and self.error:
            if "BLOCKED:" in self.error:
                return f"COMMAND_BLOCKED:{self.error.split('BLOCKED:', 1)[1].strip()}"
            return f"Error: {self.error}"
        return self.content


# ---------------------------------------------------------------------------
# Reconnect configuration
# ---------------------------------------------------------------------------

@dataclass
class ReconnectConfig:
    """Configurable reconnect strategy."""
    initial_delay: float = 1.0
    max_delay: float = 30.0
    max_retries: int = 0  # 0 = unlimited
    jitter: float = 0.1   # fraction of delay to jitter (±10%)
    backoff_factor: float = 2.0


# ---------------------------------------------------------------------------
# MCP Client
# ---------------------------------------------------------------------------

class MCPClient:
    def __init__(self):
        self.sessions: Dict[str, ClientSession] = {}
        self.tools_cache: Dict[str, Any] = {}
        self.server_tool_map: Dict[str, str] = {}
        self.exit_stack = AsyncExitStack()
        self._reconnect_tasks: Dict[str, asyncio.Task] = {}
        self._server_configs: Dict[str, dict] = {}
        self._server_stacks: Dict[str, AsyncExitStack] = {}
        # Legacy agent reference for backward compatibility
        self._agent: Any = None
        self._subagent_spawner: Optional[Callable[[str], Awaitable[str]]] = None
        self._subagent_capable: bool = False
        self._closed = False
        self._reconnect_config = ReconnectConfig()

        # Connection pool for SSE transport
        self._http_pool: Dict[str, httpx.AsyncClient] = {}

        # New subsystems
        self.permissions = ToolPermissions()
        self.permission_gate: Optional[PermissionGate] = None
        self.hooks = ToolHooks()
        self.analytics = ToolAnalytics()

        # Tool schema cache — invalidated on discover_tools
        self._schema_cache: Optional[List[Dict[str, Any]]] = None
        self._schema_cache_dirty: bool = True

    def set_reconnect_config(self, **kwargs):
        """Update reconnect parameters."""
        for k, v in kwargs.items():
            if hasattr(self._reconnect_config, k):
                setattr(self._reconnect_config, k, v)

    def set_permission_gate(self, gate: PermissionGate):
        """Set the interactive permission gate."""
        self.permission_gate = gate

    def register_subagent_spawner(self, spawn_fn: Callable[[str], Awaitable[str]]) -> None:
        """Register a callable that spawns a sub-agent given a prompt string.

        This replaces the old register_agent() which created a circular dependency.
        The spawn function receives the prompt text and returns the sub-agent's
        complete response as a string.
        """
        self._subagent_spawner = spawn_fn
        self._subagent_capable = True
        self._schema_cache_dirty = True

    def register_agent(self, agent: Any) -> None:
        """Register the agent for sub-agent spawning (task tool).

        Deprecated: use register_subagent_spawner() instead.
        This method creates a circular dependency (agent -> mcp_client -> agent).
        """
        self._agent = agent
        # Try to extract a spawn_subagent method if available
        if hasattr(agent, 'spawn_subagent'):
            self._subagent_spawner = agent.spawn_subagent
            self._subagent_capable = True
            self._agent = None  # Break circular reference; spawner is now self-contained
        else:
            # Check for common sub-agent method names
            for attr_name in ('run_subagent', 'execute_subtask', 'spawn'):
                if hasattr(agent, attr_name):
                    self._subagent_spawner = getattr(agent, attr_name)
                    self._subagent_capable = True
                    self._agent = None  # Break circular reference
                    break
            else:
                # No spawn method found; agent ref kept for legacy compatibility
                self._subagent_capable = bool(agent)
        self._schema_cache_dirty = True

    def set_permission_level(self, level: str) -> None:
        """Set the permission level for this session."""
        try:
            self.permissions.set_level(PermissionLevel(level))
            logger.info(f"Permission level set to {level}")
        except ValueError:
            logger.warning(f"Invalid permission level: {level}")

    def approve_tool(self, tool_name: str) -> None:
        """Approve a tool for one-time use."""
        self.permissions.approve_tool_once(tool_name)

    def get_hook_context(self) -> dict:
        return {
            "level": self.permissions.level.value,
            "approved_once": list(self.permissions._approved_once),
        }

    async def _close_server(self, name: str) -> None:
        """Close an individual server's session and transport."""
        old_stack = self._server_stacks.pop(name, None)
        if old_stack:
            try:
                await old_stack.aclose()
            except Exception as e:
                logger.debug(f"Error closing server {name} stack: {e}")
        self.sessions.pop(name, None)

    async def connect_servers(self, config_path: str) -> None:
        """Connect to MCP servers defined in a JSON config file."""
        try:
            loop = asyncio.get_running_loop()
            config = await asyncio.to_thread(self._load_config_sync, config_path)
        except Exception as e:
            logger.error(f"Failed to load MCP config: {e}")
            return

        for server_name, server_config in config.items():
            if isinstance(server_config, dict):
                enabled = server_config.get("enabled", True)
                if not enabled:
                    continue
                await self._connect_from_config(server_name, server_config)

    def _load_config_sync(self, config_path: str) -> dict:
        """Synchronous config loading (runs in executor to avoid blocking)."""
        with open(config_path, "r") as f:
            return json.load(f)

    async def connect_from_settings(self, servers: List[Dict]) -> None:
        """Connect to MCP servers from settings config (parallel)."""
        tasks = {}
        for server_config in servers:
            if not isinstance(server_config, dict):
                logger.warning(f"Skipping invalid server config: {server_config}")
                continue
            if not server_config.get("enabled", True):
                continue
            name = server_config.get("name")
            if not name:
                logger.warning("Skipping server config without 'name' field")
                continue
            tasks[name] = self._connect_from_config(name, server_config)
        if tasks:
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for name, r in zip(tasks, results):
                if isinstance(r, Exception):
                    logger.error(f"MCP server {name} connection failed: {r}")

    async def _connect_from_config(self, name: str, config: dict) -> None:
        """Connect a server from a config dict. Supports stdio and SSE."""
        self._server_configs[name] = config
        if "url" in config:
            ok = await self._connect_sse(name, config["url"], config.get("headers", {}))
        else:
            cmd = config.get("command")
            args = config.get("args", [])
            env = config.get("env", None)
            ok = await self._connect_transport(name, cmd, args, env, config.get("url"))
        if not ok:
            task = asyncio.create_task(self._reconnect_loop(name))
            self._reconnect_tasks[name] = task

    # ------------------------------------------------------------------ #
    # Unified transport connection (extracted to DRY _connect_server / _connect_sse)
    # ------------------------------------------------------------------ #

    async def _connect_transport(
        self,
        name: str,
        cmd: Optional[str] = None,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        url: Optional[str] = None,
        headers: Optional[dict] = None,
        timeout: float = 15.0,
    ) -> bool:
        """Connect to an MCP server via stdio (cmd/args) or SSE (url/headers).

        Extracted to eliminate the nearly-duplicate _connect_server / _connect_sse methods.
        """
        if not _MCP_AVAILABLE:
            logger.warning(f"Cannot connect to MCP server {name} — mcp package not installed")
            return False
        logger.debug(f"Connecting to MCP server: {name}" + (f" at {url}" if url else ""))
        if self._closed:
            return False

        await self._close_server(name)
        stack = AsyncExitStack()

        try:
            if url:
                # SSE transport with connection pooling
                parsed = urlparse(url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                if origin not in self._http_pool:
                    self._http_pool[origin] = httpx.AsyncClient(
                        timeout=httpx.Timeout(timeout, connect=timeout),
                    )
                pooled_client = self._http_pool[origin]

                def _pooled_client_factory():
                    return pooled_client

                transport = await asyncio.wait_for(
                    stack.enter_async_context(
                        sse_client(url, headers=headers or {}, httpx_client_factory=_pooled_client_factory)
                    ),
                    timeout=timeout,
                )
            else:
                # Stdio transport
                server_env = os.environ.copy()
                local_bin = os.path.join(os.path.expanduser("~"), ".local", "bin")
                server_env["PATH"] = f"{local_bin}:{server_env.get('PATH', '')}"
                server_env["COREPACK_ENABLE_STRICT"] = "0"
                server_env["npm_config_user_agent"] = "npm"
                if env:
                    server_env.update(env)

                server_params = StdioServerParameters(command=cmd or "", args=args or [], env=server_env)
                transport = await asyncio.wait_for(
                    stack.enter_async_context(stdio_client(server_params)),
                    timeout=timeout,
                )

            read_stream, write_stream = transport
            session = await asyncio.wait_for(
                stack.enter_async_context(ClientSession(read_stream, write_stream)),
                timeout=timeout,
            )
            await asyncio.wait_for(session.initialize(), timeout=timeout)

            self._server_stacks[name] = stack
            self.sessions[name] = session

            discovery_ok = await self._discover_tools(name, session)
            if not discovery_ok:
                # Tool discovery failed — close the server and return False
                logger.warning(f"Server {name} connected but tool discovery failed")
                await self._close_server(name)
                return False

            logger.debug(f"Connected to MCP server {name}" + (f" at {url}" if url else ""))
            return True

        except asyncio.TimeoutError:
            logger.error(f"Timeout connecting to MCP server {name} ({timeout}s)")
            await stack.aclose()
            return False
        except (asyncio.CancelledError, KeyboardInterrupt):
            await stack.aclose()
            raise
        except BaseException as e:
            logger.error(f"Failed to connect to MCP server {name}: [{type(e).__name__}] {e}")
            await stack.aclose()
            return False

    async def _connect_server(
        self, name: str, cmd: str, args: List[str],
        env: Optional[Dict[str, str]] = None, timeout: float = 15.0
    ) -> bool:
        """Connect to a stdio-based MCP server. Delegates to _connect_transport."""
        return await self._connect_transport(
            name=name, cmd=cmd, args=args, env=env, timeout=timeout,
        )

    async def _connect_sse(
        self, name: str, url: str, headers: dict = None,
        timeout: float = 15.0,
    ) -> bool:
        """Connect to a remote SSE/HTTP MCP server. Delegates to _connect_transport."""
        return await self._connect_transport(
            name=name, url=url, headers=headers or {}, timeout=timeout,
        )

    async def _discover_tools(self, name: str, session: ClientSession) -> bool:
        """Discover tools from a connected session.

        Returns True on success, False on failure.
        """
        try:
            stale = [t for t, s in self.server_tool_map.items() if s == name]
            for t in stale:
                self.tools_cache.pop(t, None)
                self.server_tool_map.pop(t, None)

            tools_response = await session.list_tools()
            for tool in tools_response.tools:
                self.tools_cache[tool.name] = tool
                self.server_tool_map[tool.name] = name
            logger.debug(f"Discovered {len(tools_response.tools)} tools from {name}")

            # Mark schema cache dirty
            self._schema_cache_dirty = True
            return True
        except Exception as e:
            logger.error(f"Failed to discover tools from {name}: {e}")
            return False

    async def _reconnect_loop(
        self,
        name: str,
        delay: Optional[float] = None,
    ) -> None:
        """Reconnect loop with configurable backoff and jitter.

        Args:
            name: Server name to reconnect.
            delay: Initial delay (uses config default if None).
        """
        config = self._server_configs.get(name, {})
        rc = self._reconnect_config
        current_delay = delay if delay is not None else rc.initial_delay
        attempts = 0

        while not self._closed:
            if rc.max_retries > 0 and attempts >= rc.max_retries:
                logger.error(f"Max retries ({rc.max_retries}) reached for {name}")
                return

            # Apply jitter: ± jitter_fraction * delay
            jitter_amount = current_delay * rc.jitter
            actual_delay = current_delay + random.uniform(-jitter_amount, jitter_amount)
            actual_delay = max(0.1, actual_delay)  # never sleep less than 100ms

            await asyncio.sleep(actual_delay)
            logger.debug(f"Reconnecting to {name}... (attempt {attempts + 1})")
            attempts += 1

            if "url" in config:
                ok = await self._connect_sse(name, config["url"], config.get("headers", {}))
            else:
                ok = await self._connect_server(
                    name,
                    config.get("command", ""),
                    config.get("args", []),
                    config.get("env"),
                )
            if ok:
                return

            current_delay = min(current_delay * rc.backoff_factor, rc.max_delay)

        if not self._closed:
            logger.error(f"Reconnect stopped for {name} (client closed)")

    def has_servers(self) -> bool:
        """True if at least one external MCP server is connected."""
        return bool(self.sessions)

    async def wait_for_tools(self, timeout: float = 10.0, min_tools: int = 1) -> bool:
        """Wait until at least `min_tools` tools are discovered, or timeout.

        Uses asyncio.Event for efficient wakeup instead of active polling.
        """
        if len(self.tools_cache) >= min_tools:
            return True
        # Fallback: poll briefly but with backoff
        t0 = time.monotonic()
        sleep = 0.05
        while time.monotonic() - t0 < timeout:
            if len(self.tools_cache) >= min_tools:
                return True
            await asyncio.sleep(min(sleep, timeout - (time.monotonic() - t0)))
            sleep = min(sleep * 1.5, 0.5)  # backoff up to 500ms
        return len(self.tools_cache) >= min_tools

    def get_tool_schema(self) -> List[Dict[str, Any]]:
        """Get OpenAI-compatible tool schema. Cached per discovery cycle."""
        if not self._schema_cache_dirty and self._schema_cache is not None:
            return self._schema_cache

        schema = []
        for name, tool in self.tools_cache.items():
            schema.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                },
            })
        if self._subagent_capable:
            schema.append({
                "type": "function",
                "function": {
                    "name": "task",
                    "description": (
                        "Spawn a sub-agent to handle a focused, self-contained task. "
                        "The sub-agent has the same capabilities (MCP tools, LLM) but runs "
                        "in an isolated context. Use this for tasks that are independent of "
                        "the current conversation. Returns the sub-agent's complete output."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "prompt": {
                                "type": "string",
                                "description": "Detailed instructions for the sub-agent",
                            },
                        },
                        "required": ["prompt"],
                    },
                },
            })
        self._schema_cache = schema
        self._schema_cache_dirty = False
        return schema

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool with permission checks, hooks, and analytics.

        Returns a string result for backward compatibility.
        Use call_tool_structured() for structured results.
        """
        result = await self.call_tool_structured(name, arguments)
        return result.to_str()

    async def call_tool_structured(self, name: str, arguments: dict) -> ToolResult:
        """Call a tool and return a structured ToolResult.

        This is the primary execution path; call_tool() wraps it for backward compatibility.
        """
        t0 = time.monotonic()
        success = False
        error: Optional[str] = None
        content = ""

        # Pre-execution checks and hooks — these run before the try block
        # so we can avoid running post-hooks for permission-denied calls.

        # 1. Permission gate (interactive)
        if self.permission_gate is not None:
            gate_allowed = await self.permission_gate.check(name, arguments)
            if not gate_allowed:
                return ToolResult(
                    success=False,
                    error=f"Tool '{name}' denied by permission gate",
                    tool_name=name,
                )

        # 2. Permission level check
        allowed, reason = self.permissions.check_tool_allowed(name)
        if not allowed:
            error = reason or f"Tool {name} not allowed"
            self.analytics.record_call(name, arguments, (time.monotonic() - t0) * 1000, success, error)
            return ToolResult(success=False, error=error, tool_name=name)

        # 3. Pre-hooks
        hook_ctx = {"tool": name, "args": arguments, "level": self.permissions.level.value}
        hook_result = await self.hooks.run_pre(name, arguments, hook_ctx)
        if hook_result and "error" in hook_result:
            error = hook_result["error"]
            self.analytics.record_call(name, arguments, (time.monotonic() - t0) * 1000, success, error)
            return ToolResult(success=False, error=error, tool_name=name)

        try:
            # 4. Execute
            if name == "task":
                if self._subagent_spawner is not None:
                    prompt = arguments.get("prompt", "")
                    content = await self._subagent_spawner(prompt)
                elif self._agent is not None and hasattr(self._agent, 'spawn_subagent'):
                    # Legacy fallback
                    prompt = arguments.get("prompt", "")
                    content = await self._agent.spawn_subagent(prompt)
                else:
                    error = "Sub-agent spawning not available"
                    self.analytics.record_call(name, arguments, (time.monotonic() - t0) * 1000, success, error)
                    return ToolResult(success=False, error=error, tool_name=name)
            elif name not in self.server_tool_map:
                error = f"Tool {name} not found"
                return ToolResult(success=False, error=error, tool_name=name)
            else:
                server_name = self.server_tool_map[name]
                session = self.sessions.get(server_name)
                if not session:
                    error = f"Session for {name} not available"
                    return ToolResult(success=False, error=error, tool_name=name)

                result_obj = await session.call_tool(name, arguments)
                if result_obj.content:
                    parts = []
                    for c in result_obj.content:
                        if c.type == "text":
                            parts.append(c.text)
                        elif c.type == "image":
                            parts.append(f"[Image: {c.mimeType} data={len(c.data)} bytes]")
                            parts.append(f"data:{c.mimeType};base64,{c.data}")
                    content = "\n".join(parts)

            success = True
            return ToolResult(success=True, content=content, tool_name=name)

        except Exception as e:
            error = str(e)
            return ToolResult(success=False, error=f"Error calling tool {name}: {error}", tool_name=name)

        finally:
            # Always record analytics and run post-hooks,
            # but only if we got past the pre-execution checks.
            # (Permission/approval failures return before the try block.)
            latency_ms = (time.monotonic() - t0) * 1000
            self.analytics.record_call(name, arguments, latency_ms, success, error)
            post_ctx = {
                "tool": name,
                "args": arguments,
                "result": error if error else content,
                "success": success,
            }
            await self.hooks.run_post(name, arguments, post_ctx)

    async def close(self) -> None:
        """Close all connections and clean up."""
        self._closed = True
        self.analytics.persist()
        tasks = [t for t in self._reconnect_tasks.values() if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._reconnect_tasks.clear()
        for name in list(self._server_stacks.keys()):
            await self._close_server(name)
        await self.exit_stack.aclose()
        self.sessions.clear()
        self.tools_cache.clear()
        self.server_tool_map.clear()
        self._schema_cache = None
        self._schema_cache_dirty = True
        # Close pooled HTTP clients
        for origin, client in self._http_pool.items():
            await client.aclose()
        self._http_pool.clear()
        self._agent = None
        self._subagent_spawner = None
        self._subagent_capable = False
