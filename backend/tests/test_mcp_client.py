import pytest


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
        assert all(t["type"] == "function" for t in schema)

    def test_call_tool_no_session(self, mcp_client):
        result = mcp_client.call_tool("nonexistent", {})
        import asyncio
        result = asyncio.run(result)
        assert "Error" in result

    def test_call_tool_structured_no_session(self, mcp_client):
        import asyncio
        result = asyncio.run(mcp_client.call_tool_structured("nonexistent", {}))
        assert result.success is False
        assert "not found" in (result.error or "")

    def test_close_cleanup(self, mcp_client):
        import asyncio
        asyncio.run(mcp_client.close())
        assert mcp_client._closed is True
        assert mcp_client.sessions == {}
        assert mcp_client.tools_cache == {}
        assert mcp_client.server_tool_map == {}

    def test_double_close_safe(self, mcp_client):
        import asyncio
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
        from backend.core.mcp.client import ToolResult
        r = ToolResult(success=True, content="hello", tool_name="test")
        assert r.to_str() == "hello"
        r2 = ToolResult(success=False, error="something broke", tool_name="test")
        assert "Error" in r2.to_str()
        r3 = ToolResult(success=False, error="BLOCKED: dangerous command", tool_name="test")
        assert r3.to_str().startswith("COMMAND_BLOCKED:")

    def test_tool_result_denied_by_permission_gate(self, mcp_client):
        """Verify that call_tool_structured returns denied result when permission_gate blocks."""
        import asyncio
        from backend.core.agent.permissions import PermissionGate

        async def deny_fn(prompt: str) -> bool:
            return False
        gate = PermissionGate(mode="ask", ask_fn=deny_fn)
        mcp_client.set_permission_gate(gate)
        result = asyncio.run(mcp_client.call_tool_structured("web_search", {"query": "test"}))
        assert result.success is False
        assert "denied by permission gate" in (result.error or "")
