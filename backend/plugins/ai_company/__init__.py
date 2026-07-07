"""
AI Company plugin — optional "thinking brain" for Amalgam.

When enabled, forwards complex tasks to the n8n AI Company harness (an
orchestrated 23-agent pipeline that plans, architects, splits, reviews,
and tests) and injects the resulting structured plan into the system
prompt *before* the main LLM call. The model then reasons from a
detailed plan rather than improvising cold.

Modes (settings: ai_company.mode):
  off    — disabled, never called
  on     — always called for every user message
  auto   — called only when the message is classified as "complex"
           (code / system design / multi-step, using the same intent
           classifier already in basic_agent.py)

The plugin is optional by design: if n8n is unreachable, the network
times out, or the pipeline returns an error, we fall back to the normal
Amalgam flow transparently and log the reason. The user never sees a
hard failure because of a misconfigured n8n setup.

Design notes:
  • Uses on_system_prompt() — the one hook the agent loop already calls,
    so no changes to basic_agent.py are needed.
  • Caches the last plan (by message fingerprint) so repeated sends of
    the same message don't re-trigger the full 23-agent pipeline.
  • Broadcasts WS events so the TUI/WebUI can show live company status.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from backend.plugins.base import BasePlugin, PluginMetadata, PluginTool

logger = logging.getLogger(__name__)

# ─── constants ────────────────────────────────────────────────────────────────

# Words/patterns that signal a task complex enough to warrant the pipeline.
# Tuned to match the same logic as BasicAgent._classify_intent().
_COMPLEX_SIGNALS = [
    "implement", "build", "create", "design", "architect",
    "refactor", "migrate", "deploy", "infrastructure",
    "system", "service", "api", "database", "integrate",
    "optimize", "performance", "scale", "security",
    "write a", "code a", "make a", "develop a",
]

_MIN_COMPLEX_LEN = 30  # chars — short messages are never routed


class AICompanyPlugin(BasePlugin):
    """
    Wires the n8n AI Company harness into the Amalgam agent loop as a
    "thinking plugin" that enriches the system prompt with a pre-built
    structured plan before the main LLM responds.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        metadata = PluginMetadata(
            name="ai_company",
            version="1.0.0",
            author="Amalgam",
            description=(
                "Optional 'thinking brain': routes complex tasks through the "
                "23-agent n8n AI Company harness and injects the resulting "
                "plan into the system prompt."
            ),
            tags=["planning", "reasoning", "n8n"],
        )
        super().__init__(metadata, config)

        cfg = config or {}
        self._mode: str = cfg.get("mode", "auto")          # off | on | auto
        self._webhook_url: str = cfg.get("webhook_url", "")
        self._timeout: float = float(cfg.get("timeout", 60.0))
        self._max_plan_tokens: int = int(cfg.get("max_plan_tokens", 800))

        # Runtime state
        self._last_message: str = ""
        self._last_plan: str = ""
        self._last_hash: str = ""
        self._active_job_id: Optional[str] = None
        self._last_duration: float = 0.0
        self._last_error: Optional[str] = None
        self._status: str = "idle"  # idle | running | done | error | disabled

        # WS broadcast callback (set externally after on_initialize)
        self._broadcast: Optional[Any] = None  # Callable[[dict], Awaitable]

        self._register_tools()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_initialize(self) -> None:
        """Validate config and register the health check."""
        if not self._webhook_url:
            logger.info(
                "ai_company: no webhook_url configured — plugin will pass through silently"
            )
        if self._mode == "off":
            self.disable()
            self._status = "disabled"
            logger.info("ai_company: mode=off, plugin disabled")
        else:
            logger.info(
                "ai_company: initialized (mode=%s, url=%s…)",
                self._mode,
                self._webhook_url[:40] if self._webhook_url else "(none)",
            )

        # Register health check with the shared registry if available
        try:
            from backend.core.deps import get_shared
            registry = get_shared().get("health_registry")
            if registry:
                registry.register("ai_company", self._health_check)
        except Exception:
            pass

    async def on_shutdown(self) -> None:
        self._status = "idle"

    # ── Core hook: system prompt injection ────────────────────────────────────

    async def on_system_prompt(self, prompt: str) -> str:
        """
        Intercept the system prompt and prepend a structured plan if the
        current message warrants it. Called by PluginRegistry.hook_system_prompt()
        which is invoked from BasicAgent._build_system_prompt() before every
        LLM call.

        The message to plan for is available on self._last_message (set by
        AICompanyPlugin.set_current_message(), which is called from handler.py).
        """
        if not self._last_message or not self._webhook_url:
            return prompt
        if self._mode == "off" or not self.is_enabled():
            return prompt
        if self._mode == "auto" and not self._is_complex(self._last_message):
            return prompt

        plan = await self._get_plan(self._last_message)
        if not plan:
            return prompt

        # Inject plan as a structured section the LLM can reason from.
        # Placed *before* the character's own system prompt so the model
        # treats it as task context, not persona override.
        plan_section = (
            "\n\n## Structured Plan (from AI Company)\n"
            "The following plan was produced by a team of specialist AI agents "
            "before you received this message. Use it as a detailed technical "
            "foundation — don't repeat it verbatim, but reason from it.\n\n"
            f"{plan}\n"
            "## End of Plan\n"
        )
        return plan_section + "\n\n" + prompt

    # ── Plan retrieval ─────────────────────────────────────────────────────────

    async def _get_plan(self, message: str) -> str:
        """
        Get a plan for *message*, using the cache if the message hasn't changed.
        Returns empty string on any failure.
        """
        msg_hash = hashlib.md5(message.encode()).hexdigest()

        # Cache hit — same message as last time
        if msg_hash == self._last_hash and self._last_plan:
            logger.debug("ai_company: plan cache hit for hash %s", msg_hash)
            return self._last_plan

        # Cache miss — call the n8n webhook
        return await self._call_webhook(message, msg_hash)

    async def _call_webhook(self, message: str, msg_hash: str) -> str:
        """
        POST to the n8n webhook and wait for the structured plan.
        Returns empty string (allowing silent fallback) on any failure.
        """
        self._status = "running"
        self._last_error = None
        self._active_job_id = f"amalgam-{int(time.time())}"
        await self._emit("company:start", {
            "job_id": self._active_job_id,
            "preview": message[:80],
        })

        t0 = time.monotonic()
        try:
            payload = {
                "task": message,
                "job_id": self._active_job_id,
                "source": "amalgam",
                "metadata": {
                    "mode": self._mode,
                    "max_plan_tokens": self._max_plan_tokens,
                },
            }
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()

            plan = self._extract_plan(data)
            if not plan:
                logger.warning("ai_company: webhook returned empty/unrecognized payload")
                self._status = "error"
                self._last_error = "empty response"
                await self._emit("company:error", {"reason": "empty response"})
                return ""

            # Trim plan to token budget (rough char-based heuristic: ~4 chars/token)
            max_chars = self._max_plan_tokens * 4
            if len(plan) > max_chars:
                plan = plan[:max_chars] + "\n… (truncated to budget)"

            self._last_plan = plan
            self._last_hash = msg_hash
            self._last_duration = time.monotonic() - t0
            self._status = "done"
            await self._emit("company:done", {
                "job_id": self._active_job_id,
                "duration": round(self._last_duration, 1),
                "plan_chars": len(plan),
            })
            logger.info(
                "ai_company: plan ready in %.1fs (%d chars)",
                self._last_duration,
                len(plan),
            )
            return plan

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            self._status = "error"
            self._last_error = f"unreachable: {e}"
            logger.warning("ai_company: webhook unreachable — %s (silent fallback)", e)
            await self._emit("company:error", {"reason": str(e)})
            return ""
        except Exception as e:
            self._status = "error"
            self._last_error = str(e)
            logger.warning("ai_company: webhook error — %s (silent fallback)", e)
            await self._emit("company:error", {"reason": str(e)})
            return ""

    # ── Response parsing ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_plan(data: Any) -> str:
        """
        Extract the plan text from the n8n webhook's JSON response.

        The harness can return several shapes:
          {"plan": "..."}                              — preferred
          {"output": {"plan": "..."}}                  — nested output node
          {"result": "..."}                            — plain result
          [{"json": {"plan": "..."}}]                  — n8n array format
          "free text plan"                             — fallback
        """
        if isinstance(data, str):
            return data.strip()

        if isinstance(data, list) and data:
            # n8n's default "Respond to Webhook" output is an array of items
            item = data[0]
            if isinstance(item, dict):
                inner = item.get("json", item)
                for key in ("plan", "output", "result", "content"):
                    if key in inner:
                        val = inner[key]
                        if isinstance(val, str):
                            return val.strip()
                        if isinstance(val, dict) and "plan" in val:
                            return str(val["plan"]).strip()

        if isinstance(data, dict):
            for key in ("plan", "result", "output", "content"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
                if isinstance(val, dict):
                    inner = val.get("plan", val.get("result", ""))
                    if inner:
                        return str(inner).strip()
        return ""

    # ── Complexity classifier ─────────────────────────────────────────────────

    def _is_complex(self, message: str) -> bool:
        """Return True if this message is complex enough to warrant the pipeline."""
        if len(message) < _MIN_COMPLEX_LEN:
            return False
        msg_lower = message.lower()
        return any(s in msg_lower for s in _COMPLEX_SIGNALS)

    # ── WS broadcast ──────────────────────────────────────────────────────────

    async def _emit(self, event: str, payload: dict) -> None:
        """
        Broadcast a status event via WebSocket so the TUI/WebUI can
        display live company status without polling. Falls back silently.
        """
        if self._broadcast is None:
            # Try to find the broadcast fn from shared state (set up in startup.py)
            try:
                from backend.core.deps import get_shared
                self._broadcast = get_shared().get("broadcast")
            except Exception:
                pass

        if callable(self._broadcast):
            try:
                msg = {"type": event, "ai_company": True, **payload}
                await self._broadcast(msg)
            except Exception as e:
                logger.debug("ai_company: _emit failed — %s", e)

    # ── Public API (called from handler.py / CLI) ─────────────────────────────

    def set_current_message(self, message: str) -> None:
        """
        Call this from the WS handler or CLI before the agent processes a
        message. The plugin stores it so on_system_prompt() knows what to
        plan for (the hook doesn't receive the raw user message itself).
        """
        self._last_message = message

    def get_status(self) -> dict:
        """Return serializable status for health checks and the /company command."""
        return {
            "mode": self._mode,
            "status": self._status,
            "webhook_url": self._webhook_url[:50] if self._webhook_url else "",
            "last_duration": self._last_duration,
            "last_error": self._last_error,
            "job_id": self._active_job_id,
            "has_plan": bool(self._last_plan),
            "plan_chars": len(self._last_plan),
        }

    def set_mode(self, mode: str) -> bool:
        """
        Change mode at runtime. Returns True if the new mode is valid.
        Persists to settings when settings are available.
        """
        if mode not in ("off", "on", "auto"):
            return False
        self._mode = mode
        if mode == "off":
            self.disable()
            self._status = "disabled"
        else:
            self.enable()
            self._status = "idle"
        return True

    # ── Health check ──────────────────────────────────────────────────────────

    async def _health_check(self) -> dict:
        """Health check: verify n8n is reachable (fast OPTIONS probe)."""
        if not self._webhook_url:
            return {"status": "ok", "detail": "not configured (optional)"}
        if self._mode == "off":
            return {"status": "ok", "detail": "disabled"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # HEAD or GET probe — n8n webhooks respond to GET with method-not-allowed
                # which still confirms connectivity. Don't send a full POST (expensive).
                r = await client.get(self._webhook_url)
                reachable = r.status_code < 500
        except Exception as e:
            return {"status": "error", "detail": f"unreachable: {e}"}
        return {
            "status": "ok" if reachable else "error",
            "detail": f"HTTP {r.status_code}",
        }

    # ── Built-in tool: run_company ─────────────────────────────────────────────

    def _register_tools(self) -> None:
        """Register a tool the LLM can call explicitly to trigger the pipeline."""
        self.register_tool(PluginTool(
            name="run_company",
            description=(
                "Trigger the AI Company — a team of 23 specialist AI agents — "
                "to plan, architect, and design a solution for a complex task. "
                "Call this when asked to build, implement, or design something "
                "substantial. Returns a structured plan you can reason from."
            ),
            func=self._tool_run_company,
            parameters={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The full task description to plan",
                    }
                },
                "required": ["task"],
            },
        ))

    async def _tool_run_company(self, task: str) -> str:
        """Tool implementation: call the company for an explicit task."""
        if not self._webhook_url:
            return "AI Company is not configured (no webhook_url set)."
        msg_hash = hashlib.md5(task.encode()).hexdigest()
        plan = await self._call_webhook(task, msg_hash)
        if not plan:
            return (
                f"AI Company was unreachable or returned an empty plan. "
                f"Error: {self._last_error or 'unknown'}. Proceeding without a plan."
            )
        return f"AI Company Plan:\n\n{plan}"


# Required by PluginManager.discover_and_load()
PluginClass = AICompanyPlugin
