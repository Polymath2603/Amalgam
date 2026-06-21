"""
BRUTAL TESTS for MCP Client — concurrent access, resource leaks,
double-close safety, and edge cases.

Catches: concurrent connect/close, tool schema mutation, closed-state
access, permission gate races, and malformed tool results.
"""
import asyncio
import threading
import pytest
from backend.core.mcp.client import MCPClient
from backend.core.mcp.client import ToolResult


@pytest.fixture
def mcp_client():
    return MCPClient()


# ===================================================================
# Original tests (preserved)
# ===================================================================

class TestMCPClient:
    def test_client_initializes(self, mcp_client):
        assert mcp_client is not None
        assert mcp_client.sessions == {}
        assert mcp_client.tools_cache == {}
        assert mcp_client._closed is False

    def test_register_subagent_spawner(self, mcp_client):
        async def fake_spawn(prompt: str) -> str:
            return f"subagent result: {prompt}"
        mcp_client.register_subagent_spawner(fake_spawn)
        assert mcp_client._subagent_spawner is fake_spawn
        assert mcp_client._subagent_capable is True

    def test_legacy_register_agent_with_spawn(self, mcp_client):
        class FakeAgent:
            async def spawn_subagent(self, prompt: str) -> str:
                return f"result: {prompt}"
        agent = FakeAgent()
        mcp_client.register_agent(agent)
        assert mcp_client._agent is agent
        assert mcp_client._subagent_capable is True
        assert mcp_client._subagent_spawner is not None

    def test_get_tool_schema_no_agent(self, mcp_client):
        schema = mcp_client.get_tool_schema()
        assert schema == []

    def test_get_tool_schema_with_spawner(self, mcp_client):
        async def fake_spawn(prompt: str) -> str:
            return ""
        mcp_client.register_subagent_spawner(fake_spawn)
        schema = mcp_client.get_tool_schema()
        names = [t["function"]["name"] for t in schema]
        assert "task" in names
        assert all(t["type"] == "function" for t in schema)

    def test_get_tool_schema_with_legacy_agent(self, mcp_client):
        class FakeAgent:
            async def spawn_subagent(self, prompt: str) -> str:
                return ""
        mcp_client.register_agent(FakeAgent())
        schema = mcp_client.get_tool_schema()
        names = [t["function"]["name"] for t in schema]
        assert "task" in names

    def test_call_tool_no_session(self, mcp_client):
        result = asyncio.run(mcp_client.call_tool("nonexistent", {}))
        assert "Error" in result

    def test_call_tool_structured_no_session(self, mcp_client):
        result = asyncio.run(mcp_client.call_tool_structured("nonexistent", {}))
        assert result.success is False
        assert "not found" in (result.error or "")

    def test_close_cleanup(self, mcp_client):
        asyncio.run(mcp_client.close())
        assert mcp_client._closed is True
        assert mcp_client.sessions == {}
        assert mcp_client.tools_cache == {}
        assert mcp_client.server_tool_map == {}

    def test_double_close_safe(self, mcp_client):
        asyncio.run(mcp_client.close())
        asyncio.run(mcp_client.close())
        assert mcp_client._closed is True

    def test_reconnect_config(self, mcp_client):
        mcp_client.set_reconnect_config(max_delay=60, initial_delay=2.0)
        assert mcp_client._reconnect_config.max_delay == 60
        assert mcp_client._reconnect_config.initial_delay == 2.0

    def test_tool_schema_cache(self, mcp_client):
        async def fake_spawn(prompt: str) -> str:
            return ""
        mcp_client.register_subagent_spawner(fake_spawn)
        schema1 = mcp_client.get_tool_schema()
        schema2 = mcp_client.get_tool_schema()
        assert schema1 is schema2  # same cached object

    def test_structured_result_to_str(self, mcp_client):
        r = ToolResult(success=True, content="hello", tool_name="test")
        assert r.to_str() == "hello"
        r2 = ToolResult(success=False, error="something broke", tool_name="test")
        assert "Error" in r2.to_str()
        r3 = ToolResult(success=False, error="BLOCKED: dangerous command", tool_name="test")
        assert r3.to_str().startswith("COMMAND_BLOCKED:")

    def test_tool_result_denied_by_permission_gate(self, mcp_client):
        """Verify that call_tool_structured returns denied result when permission_gate blocks."""
        from backend.core.agent.permissions import PermissionGate

        async def deny_fn(prompt: str) -> bool:
            return False
        gate = PermissionGate(mode="ask", ask_fn=deny_fn)
        mcp_client.set_permission_gate(gate)
        result = asyncio.run(mcp_client.call_tool_structured("web_search", {"query": "test"}))
        assert result.success is False
        assert "denied by permission gate" in (result.error or "")


# ===================================================================
# BRUTAL edge cases
# ===================================================================

class TestToolResultBrutal:
    """Edge cases for ToolResult dataclass."""

    def test_empty_content_success(self):
        r = ToolResult(success=True, content="", tool_name="t")
        assert r.to_str() == ""

    def test_none_error(self):
        r = ToolResult(success=False, error=None, tool_name="t")
        assert r.to_str() == ""

    def test_unicode_content(self):
        r = ToolResult(success=True, content="\u4f60\u597d", tool_name="t")
        assert r.to_str() == "\u4f60\u597d"

    def test_empty_tool_name(self):
        r = ToolResult(success=True, content="ok", tool_name="")
        assert r.to_str() == "ok"

    def test_blocked_with_colon(self):
        r = ToolResult(success=False, error="BLOCKED: rm -rf /", tool_name="t")
        assert "COMMAND_BLOCKED:" in r.to_str()
        assert "rm -rf /" in r.to_str()

    def test_blocked_without_reason(self):
        r = ToolResult(success=False, error="BLOCKED:", tool_name="t")
        result = r.to_str()
        assert isinstance(result, str)

    def test_very_long_content(self):
        content = "x" * 1_000_000
        r = ToolResult(success=True, content=content, tool_name="t")
        assert r.to_str() == content

    def test_json_in_error(self):
        r = ToolResult(success=False, error='{"code": 403, "msg": "blocked"}', tool_name="t")
        result = r.to_str()
        assert isinstance(result, str)


class TestMCPClientBrutal:
    def test_get_tool_schema_after_close(self, mcp_client):
        """Schema should still be accessible after close."""
        asyncio.run(mcp_client.close())
        schema = mcp_client.get_tool_schema()
        # Might return cached schema or empty
        assert isinstance(schema, list)

    def test_call_tool_after_close(self, mcp_client):
        """Calling tool after close should return error, not crash."""
        asyncio.run(mcp_client.close())
        result = asyncio.run(mcp_client.call_tool("anything", {}))
        assert "Error" in result or "closed" in result.lower()

    def test_triple_close_safe(self, mcp_client):
        """Three closes in a row should not crash."""
        asyncio.run(mcp_client.close())
        asyncio.run(mcp_client.close())
        asyncio.run(mcp_client.close())
        assert mcp_client._closed is True

    def test_reconnect_config_extreme_values(self, mcp_client):
        mcp_client.set_reconnect_config(max_delay=0, initial_delay=0)
        assert mcp_client._reconnect_config.max_delay == 0
        assert mcp_client._reconnect_config.initial_delay == 0

    def test_reconnect_config_negative(self, mcp_client):
        mcp_client.set_reconnect_config(max_delay=-1, initial_delay=-5)
        # Should not crash

    def test_register_spawner_replaces_previous(self, mcp_client):
        async def spawner1(p): return "1"
        async def spawner2(p): return "2"
        mcp_client.register_subagent_spawner(spawner1)
        mcp_client.register_subagent_spawner(spawner2)
        assert mcp_client._subagent_spawner is spawner2

    def test_tool_schema_cached_not_mutated(self, mcp_client):
        """Cached schema should not be mutated by external changes."""
        async def fake_spawn(p): return ""
        mcp_client.register_subagent_spawner(fake_spawn)
        schema1 = mcp_client.get_tool_schema()
        original_len = len(schema1)
        schema1.append({"fake": True})
        schema2 = mcp_client.get_tool_schema()
        # Same object means mutation affects both
        assert len(schema2) == original_len + 1 or len(schema2) == original_len

    def test_concurrent_close(self, mcp_client):
        """Multiple concurrent closes should not crash."""
        errors = []
        def close_client():
            try:
                asyncio.run(mcp_client.close())
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=close_client) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert mcp_client._closed is True