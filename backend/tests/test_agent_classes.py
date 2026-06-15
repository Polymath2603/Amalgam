"""Tests for BasicAgent, ReflectiveAgent, and PlanningAgent."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    llm = MagicMock()

    async def stream_impl(*args, **kwargs):
        for chunk in ["chunk1 ", "chunk2"]:
            yield chunk

    llm.stream = MagicMock(side_effect=stream_impl)
    llm.generate = AsyncMock(return_value="mock response")
    return llm


@pytest.fixture
def mock_memory():
    mem = MagicMock()
    mem.add_turn = AsyncMock()
    mem.get_session_sync = MagicMock(return_value=[])
    mem.get_recent = MagicMock(return_value=[])
    return mem


@pytest.fixture
def mock_mcp_client():
    mcp = MagicMock()
    mcp.has_servers = MagicMock(return_value=False)
    mcp.call_tool = AsyncMock(return_value="tool result")
    mcp.get_tool_schema = MagicMock(return_value=None)
    return mcp


# ===================================================================
# BasicAgent
# ===================================================================

class TestBasicAgentInit:
    def test_default_init(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, mock_memory, mcp_client=None)
        assert agent.llm is mock_llm
        assert agent.memory is mock_memory
        assert agent.mcp_client is None
        assert agent._tools == []
        assert agent._history == []

    def test_init_with_tools(self, mock_llm, mock_memory, mock_mcp_client):
        from backend.core.agent.basic_agent import BasicAgent
        tools = [{"name": "search", "fn": lambda x: x}]
        agent = BasicAgent(mock_llm, mock_memory, mock_mcp_client,
                           settings={"temp": 0.5}, tools=tools)
        assert agent.mcp_client is mock_mcp_client
        assert agent._tools == tools


class TestBasicAgentRun:
    @pytest.mark.asyncio
    async def test_yields_chunks(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, mock_memory)
        chunks = []
        async for c in agent.run("hello", {"session_id": "s1"}):
            chunks.append(c)
        assert chunks == ["chunk1 ", "chunk2"]
        mock_memory.add_turn.assert_awaited_once_with("user", "hello")

    @pytest.mark.asyncio
    async def test_stream_error_yields_error_chunk(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        mock_llm.stream.side_effect = RuntimeError("boom")
        agent = BasicAgent(mock_llm, mock_memory)
        chunks = []
        async for c in agent.run("hi", {}):
            chunks.append(c)
        assert any("Error" in c for c in chunks)


class TestBasicAgentLegacyInterface:
    @pytest.mark.asyncio
    async def test_handle_user_input(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, mock_memory)
        chunks = []
        async for c in agent.handle_user_input("hello", relationship_context="ctx"):
            chunks.append(c)
        assert chunks == ["chunk1 ", "chunk2"]

    @pytest.mark.asyncio
    async def test_get_response(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, mock_memory)
        result = await agent.get_response("hello")
        assert result == "mock response"

    @pytest.mark.asyncio
    async def test_get_response_error(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        mock_llm.generate.side_effect = RuntimeError("fail")
        agent = BasicAgent(mock_llm, mock_memory)
        result = await agent.get_response("hello")
        assert "Error" in result


class TestBasicAgentHelpers:
    def test_load_history(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        mock_memory.get_session_sync.return_value = [{"role": "user", "content": "prev"}]
        agent = BasicAgent(mock_llm, mock_memory)
        agent.load_history("sess1")
        assert agent._history == [{"role": "user", "content": "prev"}]

    def test_build_system_prompt_no_context(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, mock_memory)
        prompt = agent._build_system_prompt()
        assert "You are a helpful AI assistant" in prompt

    def test_build_system_prompt_with_context(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, mock_memory)
        prompt = agent._build_system_prompt("User likes Python")
        assert "User likes Python" in prompt

    def test_build_messages(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, mock_memory)
        msgs = agent._build_messages("hi", None, "ctx")
        assert len(msgs) == 2  # system + user
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "hi"

    def test_build_messages_with_images(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, mock_memory)
        msgs = agent._build_messages("hi", ["img1"])
        assert msgs[1].get("images") == ["img1"]

    def test_build_messages_includes_history(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, mock_memory)
        agent._history = [{"role": "assistant", "content": "prev resp"}]
        msgs = agent._build_messages("hi")
        assert len(msgs) == 3
        assert msgs[1] == {"role": "assistant", "content": "prev resp"}

    @pytest.mark.asyncio
    async def test_execute_tool_with_mcp(self, mock_llm, mock_memory, mock_mcp_client):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, mock_memory, mock_mcp_client)
        result = await agent.execute_tool("search", {"q": "test"})
        assert result == "tool result"
        mock_mcp_client.call_tool.assert_awaited_once_with("search", {"q": "test"})

    @pytest.mark.asyncio
    async def test_execute_tool_no_mcp(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, mock_memory, mcp_client=None)
        result = await agent.execute_tool("search", {"q": "test"})
        assert "No MCP client" in result

    @pytest.mark.asyncio
    async def test_get_tool_schema_from_mcp(self, mock_llm, mock_memory, mock_mcp_client):
        from backend.core.agent.basic_agent import BasicAgent
        mock_mcp_client.has_servers.return_value = True
        mock_mcp_client.get_tool_schema.return_value = [{"name": "search"}]
        agent = BasicAgent(mock_llm, mock_memory, mock_mcp_client)
        schema = await agent._get_tool_schema()
        assert schema == [{"name": "search"}]

    @pytest.mark.asyncio
    async def test_get_tool_schema_fallback(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        tools = [{"name": "search"}]
        agent = BasicAgent(mock_llm, mock_memory, tools=tools)
        schema = await agent._get_tool_schema()
        assert schema == tools


# ===================================================================
# ReflectiveAgent
# ===================================================================

class TestReflectiveAgentInit:
    def test_init_creates_inner_agent(self, mock_llm, mock_memory, mock_mcp_client):
        from backend.core.agent.reflective_agent import ReflectiveAgent
        agent = ReflectiveAgent(mock_llm, mock_memory, mock_mcp_client)
        assert agent._inner is not None
        assert agent._turn_count == 0
        assert agent._traces == []

    def test_turn_count_property(self, mock_llm, mock_memory):
        from backend.core.agent.reflective_agent import ReflectiveAgent
        agent = ReflectiveAgent(mock_llm, mock_memory)
        assert agent.turn_count == 0

    def test_traces_property(self, mock_llm, mock_memory):
        from backend.core.agent.reflective_agent import ReflectiveAgent
        agent = ReflectiveAgent(mock_llm, mock_memory)
        assert agent.traces == []


class TestReflectiveAgentRun:
    @pytest.mark.asyncio
    async def test_delegates_to_inner(self, mock_llm, mock_memory):
        from backend.core.agent.reflective_agent import ReflectiveAgent
        agent = ReflectiveAgent(mock_llm, mock_memory)
        chunks = []
        async for c in agent.run("hello", {"session_id": "s1"}):
            chunks.append(c)
        assert chunks == ["chunk1 ", "chunk2"]
        assert agent._turn_count == 1
        assert len(agent._traces) == 1

    @pytest.mark.asyncio
    async def test_run_error_yields_error_chunk(self, mock_llm, mock_memory):
        from backend.core.agent.reflective_agent import ReflectiveAgent
        agent = ReflectiveAgent(mock_llm, mock_memory)
        # Patch _inner at the instance level (it's not a class attribute)
        with patch.object(agent, "_inner") as mock_inner:
            mock_inner.run = MagicMock()
            mock_inner.run.return_value.__aiter__.side_effect = RuntimeError("fail")
            chunks = []
            async for c in agent.run("hi", {}):
                chunks.append(c)
            assert any("Error" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_reflection_triggers_after_n_turns(self, mock_llm, mock_memory):
        from backend.core.agent.reflective_agent import REFLECTION_EVERY_N
        from backend.core.agent.reflective_agent import ReflectiveAgent
        agent = ReflectiveAgent(mock_llm, mock_memory)
        with patch.object(agent, "_reflect", new=AsyncMock()) as mock_reflect:
            for _ in range(REFLECTION_EVERY_N):
                async for _ in agent.run("t", {"session_id": "s1"}):
                    pass
            assert agent._turn_count == 0  # reset after reflection
            mock_reflect.assert_awaited_once()


class TestReflectiveAgentInterfaces:
    @pytest.mark.asyncio
    async def test_handle_user_input(self, mock_llm, mock_memory):
        from backend.core.agent.reflective_agent import ReflectiveAgent
        agent = ReflectiveAgent(mock_llm, mock_memory)
        chunks = []
        async for c in agent.handle_user_input("hello", relationship_context="ctx"):
            chunks.append(c)
        assert chunks == ["chunk1 ", "chunk2"]

    @pytest.mark.asyncio
    async def test_get_response(self, mock_llm, mock_memory):
        from backend.core.agent.reflective_agent import ReflectiveAgent
        agent = ReflectiveAgent(mock_llm, mock_memory)
        result = await agent.get_response("hello")
        assert result == "mock response"

    def test_load_history(self, mock_llm, mock_memory):
        from backend.core.agent.reflective_agent import ReflectiveAgent
        agent = ReflectiveAgent(mock_llm, mock_memory)
        with patch.object(agent._inner, "load_history") as mock_lh:
            agent.load_history("s1")
            mock_lh.assert_called_once_with("s1")


# ===================================================================
# PlanningAgent
# ===================================================================

class TestPlanningAgentClassify:
    @pytest.mark.parametrize("msg,expected", [
        ("what is the weather", "simple"),
        ("who is the president", "simple"),
        ("tell me about Python", "simple"),
        ("search for cats", "simple"),
        ("calculate 2+2", "simple"),
        ("remind me to buy milk", "simple"),
        ("random text", "compound"),
        ("what is X and also Y", "simple"),
        ("first do this, then that", "compound"),
        ("analyze this data", "compound"),
        ("Sentence one. Sentence two. Sentence three.", "compound"),
    ])
    def test_classify_task(self, msg, expected):
        from backend.core.agent.planning_agent import PlanningAgent
        assert PlanningAgent._classify_task(msg) == expected


class TestPlanningAgentInit:
    def test_init_creates_inner(self, mock_llm, mock_memory, mock_mcp_client):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_memory, mock_mcp_client,
                              settings={}, tools=[])
        assert agent._inner is not None


class TestPlanningAgentRun:
    @pytest.mark.asyncio
    async def test_simple_task_fast_path(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_memory)
        chunks = []
        async for c in agent.run("what is Python", {"session_id": "s1"}):
            chunks.append(c)
        # Should take fast path — no planning prefix
        assert chunks == ["chunk1 ", "chunk2"]

    @pytest.mark.asyncio
    async def test_compound_task_planning_flow(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_memory)
        # Patch _decompose_task to return controlled steps
        agent._decompose_task = AsyncMock(return_value=[
            {"description": "Step one"},
            {"description": "Step two"},
        ])
        # Patch _execute_step to return controlled strings
        agent._execute_step = AsyncMock(side_effect=["result1", "result2"])
        chunks = []
        async for c in agent.run("analyze and compare X and Y", {"session_id": "s1"}):
            chunks.append(c)
        full = "".join(chunks)
        assert "Planning" in full
        assert "Step one" in full
        assert "Step two" in full
        assert "Synthesizing" in full

    @pytest.mark.asyncio
    async def test_fallback_when_decomposition_fails(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_memory)
        agent._decompose_task = AsyncMock(return_value=[])
        chunks = []
        async for c in agent.run("analyze X", {"session_id": "s1"}):
            chunks.append(c)
        # Falls back to inner agent after planning prefix
        assert chunks == ["[Planning] Breaking down your request...\n\n", "chunk1 ", "chunk2"]

    @pytest.mark.asyncio
    async def test_step_error_handling(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_memory)
        agent._decompose_task = AsyncMock(return_value=[
            {"description": "Fail step"},
        ])
        agent._execute_step = AsyncMock(side_effect=RuntimeError("step fail"))
        chunks = []
        async for c in agent.run("analyze X", {"session_id": "s1"}):
            chunks.append(c)
        full = "".join(chunks)
        assert "Error in step 1" in full


class TestPlanningAgentDecompose:
    @pytest.mark.asyncio
    async def test_decompose_success(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        mock_llm.generate = AsyncMock(return_value='[{"description": "Step 1"}, {"description": "Step 2"}]')
        agent = PlanningAgent(mock_llm, mock_memory)
        steps = await agent._decompose_task("do X and Y", {})
        assert len(steps) == 2
        assert steps[0]["description"] == "Step 1"

    @pytest.mark.asyncio
    async def test_decompose_strips_code_fence(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        mock_llm.generate = AsyncMock(
            return_value='```json\n[{"description": "Step 1"}]\n```'
        )
        agent = PlanningAgent(mock_llm, mock_memory)
        steps = await agent._decompose_task("do X", {})
        assert len(steps) == 1

    @pytest.mark.asyncio
    async def test_decompose_returns_empty_on_bad_json(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        mock_llm.generate = AsyncMock(return_value="not json")
        agent = PlanningAgent(mock_llm, mock_memory)
        steps = await agent._decompose_task("do X", {})
        assert steps == []

    @pytest.mark.asyncio
    async def test_decompose_returns_empty_on_llm_error(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        mock_llm.generate.side_effect = RuntimeError("LLM down")
        agent = PlanningAgent(mock_llm, mock_memory)
        steps = await agent._decompose_task("do X", {})
        assert steps == []

    @pytest.mark.asyncio
    async def test_decompose_caps_at_five_steps(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        many_steps = [{"description": f"S{i}"} for i in range(10)]
        mock_llm.generate = AsyncMock(return_value=json.dumps(many_steps))
        agent = PlanningAgent(mock_llm, mock_memory)
        steps = await agent._decompose_task("big task", {})
        assert len(steps) == 5


class TestPlanningAgentSynthesize:
    @pytest.mark.asyncio
    async def test_synthesize_yields_chunks(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_memory)
        results = [{"step": 1, "description": "S1", "result": "out1"}]
        chunks = []
        async for c in agent._synthesize("test", results, {}):
            chunks.append(c)
        assert chunks == ["chunk1 ", "chunk2"]


class TestPlanningAgentInterfaces:
    @pytest.mark.asyncio
    async def test_handle_user_input(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_memory)
        chunks = []
        async for c in agent.handle_user_input("hello", relationship_context="ctx"):
            chunks.append(c)
        # "hello" is classified as "compound" by default, yielding the planning prefix
        # then decomposition fails and falls back to inner agent
        assert chunks == ["[Planning] Breaking down your request...\n\n", "chunk1 ", "chunk2"]

    @pytest.mark.asyncio
    async def test_get_response(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_memory)
        result = await agent.get_response("hello")
        assert result == "mock response"

    def test_load_history(self, mock_llm, mock_memory):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_memory)
        with patch.object(agent._inner, "load_history") as mock_lh:
            agent.load_history("s1")
            mock_lh.assert_called_once_with("s1")
