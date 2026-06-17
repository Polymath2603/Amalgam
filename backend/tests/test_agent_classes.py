"""Tests for BasicAgent, ReflectiveAgent, and PlanningAgent (plan spec)."""

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
    llm.complete = AsyncMock(return_value="mock completion")
    return llm


@pytest.fixture
def mock_memory():
    mem = MagicMock()
    mem.add_turn = AsyncMock()
    mem.get_session_sync = MagicMock(return_value=[])
    mem.get_recent = MagicMock(return_value=[])
    return mem


@pytest.fixture
def mock_tools():
    return {}


# ===================================================================
# BaseAgent
# ===================================================================

class TestBaseAgent:
    def test_tool_call_dataclass(self):
        from backend.core.agent.base import ToolCall
        tc = ToolCall(name="search", input={"q": "test"}, output="result", success=True)
        assert tc.name == "search"
        assert tc.input == {"q": "test"}
        assert tc.output == "result"
        assert tc.success is True

    def test_agent_trace_is_complex(self):
        from backend.core.agent.base import AgentTrace, ToolCall
        trace = AgentTrace(session_id="s1", user_message="hi")
        assert trace.is_complex is False
        trace.tool_calls = [ToolCall("t1", {}, "ok")] * 5
        assert trace.is_complex is True

    def test_agent_trace_not_complex(self):
        from backend.core.agent.base import AgentTrace
        trace = AgentTrace(session_id="s1", user_message="hi")
        trace.tool_calls = [MagicMock() for _ in range(3)]
        assert trace.is_complex is False


# ===================================================================
# BasicAgent
# ===================================================================

class TestBasicAgentInit:
    def test_default_init(self, mock_llm):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm)
        assert agent.llm is mock_llm
        assert agent.tools == {}
        assert agent.memory is None
        assert agent.config == {}

    def test_init_with_tools(self, mock_llm, mock_memory, mock_tools):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, tools=mock_tools, memory=mock_memory,
                           config={"temp": 0.5})
        assert agent.tools == mock_tools
        assert agent.memory is mock_memory
        assert agent.config == {"temp": 0.5}


class TestBasicAgentRun:
    @pytest.mark.asyncio
    async def test_yields_chunks(self, mock_llm, mock_memory):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm, memory=mock_memory)
        chunks = []
        async for c in agent.run("hello", {"session_id": "s1"}):
            chunks.append(c)
        assert len(chunks) > 0


class TestBasicAgentExecuteTool:
    @pytest.mark.asyncio
    async def test_execute_known_tool(self, mock_llm):
        from backend.core.agent.base import ToolCall
        from backend.core.agent.basic_agent import BasicAgent
        async def fake_tool(**kwargs):
            return f"ran with {kwargs}"
        tools = {"my_tool": fake_tool}
        agent = BasicAgent(mock_llm, tools=tools)
        tc = await agent.execute_tool("my_tool", {"x": 1})
        assert isinstance(tc, ToolCall)
        assert tc.success is True
        assert "ran with" in tc.output

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, mock_llm):
        from backend.core.agent.basic_agent import BasicAgent
        agent = BasicAgent(mock_llm)
        tc = await agent.execute_tool("nonexistent", {})
        assert tc.success is False
        assert "unknown tool" in tc.output.lower()

    @pytest.mark.asyncio
    async def test_execute_failing_tool(self, mock_llm):
        from backend.core.agent.basic_agent import BasicAgent
        async def broken(**kwargs):
            raise ValueError("boom")
        tools = {"broken": broken}
        agent = BasicAgent(mock_llm, tools=tools)
        tc = await agent.execute_tool("broken", {})
        assert tc.success is False
        assert "Tool error" in tc.output


# ===================================================================
# ReflectiveAgent
# ===================================================================

class TestReflectiveAgentInit:
    def test_init_with_inner(self, mock_llm, mock_memory, mock_tools):
        from backend.core.agent.reflective_agent import ReflectiveAgent
        from backend.core.agent.basic_agent import BasicAgent
        inner = BasicAgent(mock_llm, tools=mock_tools, memory=mock_memory)
        agent = ReflectiveAgent(inner, mock_llm, mock_tools, mock_memory, {})
        assert agent.inner is inner
        assert agent._turn_count == 0


class TestReflectiveAgentRun:
    @pytest.mark.asyncio
    async def test_delegates_to_inner(self, mock_llm, mock_memory, mock_tools):
        from backend.core.agent.reflective_agent import ReflectiveAgent
        from backend.core.agent.basic_agent import BasicAgent
        inner = BasicAgent(mock_llm, tools=mock_tools, memory=mock_memory)
        agent = ReflectiveAgent(inner, mock_llm, mock_tools, mock_memory, {})
        chunks = []
        async for c in agent.run("hello", {"session_id": "s1"}):
            chunks.append(c)
        assert len(chunks) > 0
        assert agent._turn_count == 1


# ===================================================================
# PlanningAgent
# ===================================================================

class TestPlanningAgentInit:
    def test_init(self, mock_llm, mock_memory, mock_tools):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_tools, mock_memory, {})
        assert agent.llm is mock_llm
        assert agent.tools == mock_tools


class TestPlanningAgentClassify:
    def test_is_compound_positive(self):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(None, {}, None, {})
        msg = ("first analyze the data, and then write a report, "
               "and also check for errors, and finally send an email to the team about results")
        assert agent._is_compound(msg) is True

    def test_is_compound_short_message(self):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(None, {}, None, {})
        # Short message with compound signal but < 15 words
        assert agent._is_compound("first this then that") is False

    def test_is_compound_negative(self):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(None, {}, None, {})
        assert agent._is_compound("what is the weather") is False


class TestPlanningAgentDecompose:
    @pytest.mark.asyncio
    async def test_decompose_success(self, mock_llm):
        from backend.core.agent.planning_agent import PlanningAgent
        mock_llm.complete = AsyncMock(
            return_value='[{"title": "Step 1", "instruction": "Do step 1"}, {"title": "Step 2", "instruction": "Do step 2"}]'
        )
        agent = PlanningAgent(mock_llm, {}, None, {})
        steps = await agent._decompose("do X and Y", {})
        assert len(steps) == 2
        assert steps[0]["title"] == "Step 1"

    @pytest.mark.asyncio
    async def test_decompose_strips_code_fence(self, mock_llm):
        from backend.core.agent.planning_agent import PlanningAgent
        mock_llm.complete = AsyncMock(
            return_value='```json\n[{"title": "Step 1", "instruction": "Do step 1"}]\n```'
        )
        agent = PlanningAgent(mock_llm, {}, None, {})
        steps = await agent._decompose("do X", {})
        assert len(steps) == 1

    @pytest.mark.asyncio
    async def test_decompose_returns_empty_on_bad_json(self, mock_llm):
        from backend.core.agent.planning_agent import PlanningAgent
        mock_llm.complete = AsyncMock(return_value="not json")
        agent = PlanningAgent(mock_llm, {}, None, {})
        steps = await agent._decompose("do X", {})
        assert steps == []

    @pytest.mark.asyncio
    async def test_decompose_returns_empty_on_llm_error(self, mock_llm):
        from backend.core.agent.planning_agent import PlanningAgent
        mock_llm.complete.side_effect = RuntimeError("LLM down")
        agent = PlanningAgent(mock_llm, {}, None, {})
        steps = await agent._decompose("do X", {})
        assert steps == []

    @pytest.mark.asyncio
    async def test_decompose_caps_at_five_steps(self, mock_llm):
        from backend.core.agent.planning_agent import PlanningAgent
        many_steps = [{"title": f"S{i}", "instruction": f"Do {i}"} for i in range(10)]
        mock_llm.complete = AsyncMock(return_value=json.dumps(many_steps))
        agent = PlanningAgent(mock_llm, {}, None, {})
        steps = await agent._decompose("big task", {})
        assert len(steps) == 5


class TestPlanningAgentRun:
    @pytest.mark.asyncio
    async def test_simple_task_fast_path(self, mock_llm, mock_memory, mock_tools):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_tools, mock_memory, {})
        chunks = []
        async for c in agent.run("what is Python", {"session_id": "s1"}):
            chunks.append(c)
        # Should take fast path
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_fallback_when_decomposition_fails(self, mock_llm, mock_memory, mock_tools):
        from backend.core.agent.planning_agent import PlanningAgent
        agent = PlanningAgent(mock_llm, mock_tools, mock_memory, {})
        # Force a compound classification with a long message containing signals
        agent._is_compound = MagicMock(return_value=True)
        agent._decompose = AsyncMock(return_value=[])
        chunks = []
        async for c in agent.run("first do X, and then do Y, and also check Z please", {"session_id": "s1"}):
            chunks.append(c)
        # Falls back to basic agent after planning prefix
        assert len(chunks) >= 2


# ===================================================================
# AgentFactory
# ===================================================================

class TestAgentFactory:
    def test_create_basic(self):
        from backend.core.agent.factory import AgentFactory
        from backend.core.agent.basic_agent import BasicAgent
        agent = AgentFactory.create("basic", None, {}, None, {})
        assert isinstance(agent, BasicAgent)

    def test_create_planning(self):
        from backend.core.agent.factory import AgentFactory
        from backend.core.agent.planning_agent import PlanningAgent
        agent = AgentFactory.create("planning", None, {}, None, {})
        assert isinstance(agent, PlanningAgent)

    def test_create_reflective(self):
        from backend.core.agent.factory import AgentFactory
        from backend.core.agent.reflective_agent import ReflectiveAgent
        agent = AgentFactory.create("reflective", None, {}, None, {})
        assert isinstance(agent, ReflectiveAgent)

    def test_create_reflective_planning(self):
        from backend.core.agent.factory import AgentFactory
        from backend.core.agent.reflective_agent import ReflectiveAgent
        agent = AgentFactory.create("reflective_planning", None, {}, None, {})
        assert isinstance(agent, ReflectiveAgent)

    def test_create_unknown_raises(self):
        from backend.core.agent.factory import AgentFactory
        import pytest
        with pytest.raises(ValueError):
            AgentFactory.create("unknown", None, {}, None, {})
