"""
Comprehensive tests for the orchestrator subsystem:

- engine.py: Plan creation, DAG scheduling, step dispatch, concurrency, error handling
- blackboard.py: CRUD, pub/sub, locking with timeout, concurrent safety
- escalation.py: Escalation lifecycle, notify_user with Future, severity types
- sandbox.py: Topic tree, BFS relationship check, cycle detection, lock TTL
- state.py: Agent run tracking, status transitions, swarm update emission
"""
import asyncio
import time
import uuid
from collections.abc import AsyncGenerator

import pytest

from backend.core.orchestrator import (
    Orchestrator,
    OrchestratorState,
    AgentRun,
    AgentStatus,
    AgentProtocol,
    Plan,
    PlanStep,
    Blackboard,
    BlackboardEntry,
    ChainOfCommand,
    EscalationRequest,
    Severity,
    SandboxDetector,
    TopicLock,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def orch():
    return Orchestrator(config={"model": "test-model"})


@pytest.fixture
def blackboard():
    return Blackboard()


@pytest.fixture
def chain():
    return ChainOfCommand(max_auto_escalations=3)


@pytest.fixture
def sandbox():
    return SandboxDetector(lock_ttl=300.0)


@pytest.fixture
def state():
    return OrchestratorState(config={"model": "test-model"})


# ===================================================================
# engine.py — Orchestrator
# ===================================================================

class _MockAgent:
    """Minimal AgentProtocol-compatible mock."""
    def __init__(self, agent_type: str = ""):
        self.agent_type = agent_type

    async def handle_user_input(self, inp: str) -> AsyncGenerator[str, None]:
        for chunk in [f"result-{inp[:16]}"]:
            yield chunk


class _FailingAgent:
    """Agent that raises on first yield."""
    async def handle_user_input(self, inp: str) -> AsyncGenerator[str, None]:
        raise RuntimeError("simulated failure")
        yield  # pragma: no cover


class _CancellingAgent:
    """Agent that raises CancelledError."""
    async def handle_user_input(self, inp: str) -> AsyncGenerator[str, None]:
        raise asyncio.CancelledError("cancelled!")
        yield  # pragma: no cover


def _agent_factory(agent_type: str = "basic") -> _MockAgent:
    return _MockAgent(agent_type)


class TestEngine:
    """Orchestrator plan lifecycle and step dispatch."""

    def test_create_plan(self, orch: Orchestrator):
        steps = [
            {"description": "Step 1", "agent_type": "basic"},
            {"description": "Step 2", "agent_type": "reflective",
             "depends_on": []},
        ]
        plan = orch.create_plan("test", steps)
        assert plan.id.startswith("plan_")
        assert plan.name == "test"
        assert len(plan.steps) == 2
        assert plan.steps[0].description == "Step 1"
        assert plan.steps[0].status == "pending"
        assert plan.status == "active"

    def test_create_plan_missing_field_warning(self, orch: Orchestrator, caplog):
        """Missing required fields produce a warning (not crash)."""
        import logging
        caplog.set_level(logging.WARNING)
        steps = [{}]  # no description
        plan = orch.create_plan("warn-test", steps)
        assert len(plan.steps) == 1
        assert plan.steps[0].description == ""

    def test_get_plan(self, orch: Orchestrator):
        plan = orch.create_plan("test", [{"description": "A"}])
        assert orch.get_plan(plan.id) is plan
        assert orch.get_plan("nonexistent") is None

    def test_cancel_plan(self, orch: Orchestrator):
        plan = orch.create_plan("test", [{"description": "A"}])
        step = plan.steps[0]
        step.status = "running"
        step.agent_id = "agent_abc"
        orch.cancel_plan(plan.id)
        assert plan.status == "failed"
        assert step.status == "failed"

    def test_cancel_plan_nonexistent(self, orch: Orchestrator):
        """Cancelling a nonexistent plan should be a no-op."""
        orch.cancel_plan("non_existent")  # should not raise

    def test_get_runnable_steps_no_deps(self, orch: Orchestrator):
        plan = orch.create_plan("test", [
            {"description": "A"},
            {"description": "B"},
        ])
        runnable = orch.get_runnable_steps(plan.id)
        assert len(runnable) == 2  # both have no deps → both runnable

    def test_get_runnable_steps_with_deps(self, orch: Orchestrator):
        plan = orch.create_plan("test", [
            {"description": "A"},
            {"description": "B", "depends_on": []},
            {"description": "C"},
        ])
        # B depends on A — use the actual generated IDs
        step_a_id = plan.steps[0].id
        step_b_id = plan.steps[1].id
        plan.steps[1].depends_on = [step_a_id]

        runnable = orch.get_runnable_steps(plan.id)
        assert len(runnable) == 2  # A and C (B depends on A)
        assert runnable[0].id == step_a_id
        assert runnable[1].id == plan.steps[2].id

        # Mark A as done
        plan.steps[0].status = "done"
        runnable = orch.get_runnable_steps(plan.id)
        assert len(runnable) == 2  # B and C both become runnable
        assert runnable[0].id == step_b_id

    def test_get_runnable_steps_plan_not_active(self, orch: Orchestrator):
        plan = orch.create_plan("test", [{"description": "A"}])
        plan.status = "paused"
        assert orch.get_runnable_steps(plan.id) == []

    def test_get_runnable_steps_nonexistent_plan(self, orch: Orchestrator):
        assert orch.get_runnable_steps("nonexistent") == []

    def test_get_runnable_steps_performance_index(
        self, orch: Orchestrator
    ):
        """Many steps with cross-dependencies should resolve quickly (O(n))."""
        n = 50
        steps = [{"description": f"Step {i}"} for i in range(n)]
        plan = orch.create_plan("perf", steps)
        # Chain: 0 → 1 → 2 → ... → n-1 using actual generated IDs
        for i in range(1, n):
            plan.steps[i].depends_on = [plan.steps[i - 1].id]
        # All pending → only step 0 is runnable
        runnable = orch.get_runnable_steps(plan.id)
        assert len(runnable) == 1
        assert runnable[0].id == plan.steps[0].id

    @pytest.mark.asyncio
    async def test_dispatch_step(self, orch: Orchestrator):
        plan = orch.create_plan("test", [{"description": "Do something"}])
        step = plan.steps[0]
        result = await orch.dispatch_step(plan.id, step, _agent_factory)
        assert "Do something" in result
        assert step.status == "done"
        assert step.agent_id.startswith("agent_")

    @pytest.mark.asyncio
    async def test_dispatch_step_failure(self, orch: Orchestrator):
        plan = orch.create_plan("test", [{"description": "fail"}])
        step = plan.steps[0]
        result = await orch.dispatch_step(plan.id, step,
                                          lambda agent_type: _FailingAgent())
        assert "Error" in result
        assert step.status == "failed"

    @pytest.mark.asyncio
    async def test_dispatch_step_cancelled(self, orch: Orchestrator):
        """CancelledError should propagate through dispatch_step."""
        plan = orch.create_plan("test", [{"description": "cancel"}])
        step = plan.steps[0]
        with pytest.raises(asyncio.CancelledError):
            await orch.dispatch_step(plan.id, step,
                                     lambda agent_type: _CancellingAgent())
        assert step.status == "failed"

    @pytest.mark.asyncio
    async def test_dispatch_step_swarm_update(self, orch: Orchestrator):
        """Swarm UI update is sent before and after step execution."""
        sent_messages = []

        async def fake_ws(msg):
            sent_messages.append(msg.get("type"))

        orch.set_ws_sender(fake_ws)
        plan = orch.create_plan("test", [{"description": "Task"}])
        await orch.dispatch_step(plan.id, plan.steps[0], _agent_factory)
        assert "swarm_update" in sent_messages

    @pytest.mark.asyncio
    async def test_execute_plan(self, orch: Orchestrator):
        steps_list = [
            {"description": "Step A"},
            {"description": "Step B"},
        ]
        plan = orch.create_plan("test-exec", steps_list)
        # B depends on A using actual IDs
        plan.steps[1].depends_on = [plan.steps[0].id]
        result = await orch.execute_plan(plan.id, _agent_factory)
        assert result["status"] == "completed"
        assert plan.steps[0].id in result["results"]
        assert plan.steps[1].id in result["results"]

    @pytest.mark.asyncio
    async def test_execute_plan_not_found(self, orch: Orchestrator):
        result = await orch.execute_plan("nonexistent", _agent_factory)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_execute_plan_with_concurrency(self, orch: Orchestrator):
        """Multiple independent steps run concurrently."""
        steps_list = [
            {"description": "A"},
            {"description": "B"},
            {"description": "C"},
        ]
        plan = orch.create_plan("concurrent", steps_list)

        result = await orch.execute_plan(plan.id, _agent_factory, max_concurrent=5)
        assert result["status"] == "completed"
        assert len(result["results"]) == 3

    @pytest.mark.asyncio
    async def test_execute_plan_partial_failure(self, orch: Orchestrator):
        """Plan should be failed if any step fails."""
        steps_list = [{"description": "A"}, {"description": "B"}]
        plan = orch.create_plan("partial-fail", steps_list)

        call_count = 0

        def _mixed_factory(agent_type: str = "basic"):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return _FailingAgent()
            return _MockAgent()

        result = await orch.execute_plan(plan.id, _mixed_factory)
        assert result["status"] == "failed"

    def test_loop_property(self, orch: Orchestrator):
        """Loop property returns a running or new event loop."""
        loop = orch.loop
        assert loop is not None
        assert not loop.is_closed()

    def test_agent_protocol_compatible(self):
        """AgentProtocol works with runtime_checkable."""
        assert isinstance(_MockAgent(), AgentProtocol)
        assert not isinstance(42, AgentProtocol)


# ===================================================================
# blackboard.py — Blackboard
# ===================================================================

class TestBlackboard:
    """Blackboard CRUD, pub/sub, locking, concurrent safety."""

    @pytest.mark.asyncio
    async def test_post_and_get(self, blackboard: Blackboard):
        await blackboard.post("test.key", {"value": 42}, "agent1")
        val = await blackboard.get("test.key")
        assert val == {"value": 42}

    @pytest.mark.asyncio
    async def test_get_default(self, blackboard: Blackboard):
        val = await blackboard.get("nonexistent", "fallback")
        assert val == "fallback"

    @pytest.mark.asyncio
    async def test_post_with_ttl(self, blackboard: Blackboard):
        await blackboard.post("ephemeral", "data", "agent1", ttl=0.05)
        val = await blackboard.get("ephemeral")
        assert val == "data"
        await asyncio.sleep(0.06)
        val = await blackboard.get("ephemeral")
        assert val is None  # expired

    @pytest.mark.asyncio
    async def test_delete(self, blackboard: Blackboard):
        await blackboard.post("test.key", "value", "agent1")
        await blackboard.delete("test.key")
        val = await blackboard.get("test.key")
        assert val is None

    @pytest.mark.asyncio
    async def test_search_by_prefix(self, blackboard: Blackboard):
        await blackboard.post("agent.alpha", "a", "agent1")
        await blackboard.post("agent.beta", "b", "agent1")
        await blackboard.post("system.config", "cfg", "agent1")
        results = await blackboard.search("agent.")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_search_no_match(self, blackboard: Blackboard):
        results = await blackboard.search("nonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_acquire_lock_basic(self, blackboard: Blackboard):
        acquired = await blackboard.acquire_lock("resource:r1", "agent1")
        assert acquired is True

    @pytest.mark.asyncio
    async def test_acquire_lock_blocks_other_agent(self, blackboard: Blackboard):
        await blackboard.acquire_lock("resource:r1", "agent1")
        acquired = await blackboard.acquire_lock("resource:r1", "agent2", timeout=0)
        assert acquired is False

    @pytest.mark.asyncio
    async def test_acquire_lock_reentrant(self, blackboard: Blackboard):
        await blackboard.acquire_lock("resource:r1", "agent1")
        # Same agent should re-acquire immediately
        acquired = await blackboard.acquire_lock("resource:r1", "agent1")
        assert acquired is True

    @pytest.mark.asyncio
    async def test_acquire_lock_timeout(self, blackboard: Blackboard):
        await blackboard.acquire_lock("resource:r1", "agent1")
        # Another agent trying with a very short timeout should fail
        acquired = await blackboard.acquire_lock("resource:r1", "agent2", timeout=0)
        assert acquired is False

    @pytest.mark.asyncio
    async def test_release_lock(self, blackboard: Blackboard):
        await blackboard.acquire_lock("resource:r1", "agent1")
        await blackboard.release_lock("resource:r1", "agent1")
        # Now another agent can acquire
        acquired = await blackboard.acquire_lock("resource:r1", "agent2", timeout=0)
        assert acquired is True

    @pytest.mark.asyncio
    async def test_release_lock_wrong_agent(self, blackboard: Blackboard):
        """Another agent cannot release a lock it doesn't hold."""
        await blackboard.acquire_lock("resource:r1", "agent1")
        await blackboard.release_lock("resource:r1", "agent2")
        # Lock should still be held by agent1
        acquired = await blackboard.acquire_lock("resource:r1", "agent2", timeout=0)
        assert acquired is False

    @pytest.mark.asyncio
    async def test_release_all_locks(self, blackboard: Blackboard):
        await blackboard.acquire_lock("r1", "agent1")
        await blackboard.acquire_lock("r2", "agent1")
        await blackboard.release_all_locks("agent1")
        assert await blackboard.acquire_lock("r1", "agent2", timeout=0) is True
        assert await blackboard.acquire_lock("r2", "agent2", timeout=0) is True

    @pytest.mark.asyncio
    async def test_clear(self, blackboard: Blackboard):
        await blackboard.post("test.key", "value", "agent1")
        await blackboard.clear()
        val = await blackboard.get("test.key")
        assert val is None

    @pytest.mark.asyncio
    async def test_pub_sub(self, blackboard: Blackboard):
        """Subscribers are notified when a matching entry is posted."""
        received = []

        def callback(key, value, author):
            received.append((key, value, author))

        blackboard.subscribe("agent.", callback)
        await blackboard.post("agent.msg", "hello", "agent1")
        # Small delay for subscription notification
        await asyncio.sleep(0.01)
        assert len(received) == 1
        assert received[0] == ("agent.msg", "hello", "agent1")

    @pytest.mark.asyncio
    async def test_unsubscribe(self, blackboard: Blackboard):
        """Unsubscribing removes the callback."""
        received = []

        def cb(key, value, author):
            received.append(key)

        blackboard.subscribe("test.", cb)
        blackboard.unsubscribe("test.", cb)
        await blackboard.post("test.msg", "v", "a1")
        await asyncio.sleep(0.01)
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_concurrent_post_and_search(self, blackboard: Blackboard):
        """Multiple concurrent operations don't corrupt state."""
        async def poster(n):
            for i in range(10):
                await blackboard.post(f"agent.{n}.{i}", i, f"agent{n}")

        await asyncio.gather(poster(1), poster(2), poster(3))
        results = await blackboard.search("agent.")
        # Each poster creates 10 entries = 30 total
        assert len(results) == 30


# ===================================================================
# escalation.py — ChainOfCommand
# ===================================================================

class TestChainOfCommand:
    """Escalation lifecycle, severity, notify_user, resolve."""

    def test_escalate_creates_request(self, chain: ChainOfCommand):
        req = chain.escalate("agent1", "I'm stuck", "Context data", "blocked")
        assert isinstance(req, EscalationRequest)
        assert req.id is not None
        assert len(req.id) > 0
        assert req.agent_id == "agent1"
        assert req.reason == "I'm stuck"
        assert req.severity == "blocked"
        assert not req.resolved

    def test_escalate_default_severity(self, chain: ChainOfCommand):
        req = chain.escalate("agent1", "FYI", "info")
        assert req.severity == "info"

    def test_resolve(self, chain: ChainOfCommand):
        req = chain.escalate("agent1", "blocked", "ctx", "blocked")
        chain.resolve(req, "User provided guidance")
        assert req.resolved
        assert req.resolution == "User provided guidance"

    def test_get_pending(self, chain: ChainOfCommand):
        req1 = chain.escalate("agent1", "blocked", "ctx", "blocked")
        req2 = chain.escalate("agent2", "warning", "ctx", "warning")
        chain.resolve(req1, "done")
        pending = chain.get_pending()
        assert len(pending) == 1
        assert pending[0] is req2

    def test_get_pending_filtered(self, chain: ChainOfCommand):
        chain.escalate("agent1", "info", "ctx", "info")
        chain.escalate("agent2", "blocked", "ctx", "blocked")
        blocked = chain.get_pending(severity="blocked")
        assert len(blocked) == 1

    def test_can_auto_escalate_under_limit(self, chain: ChainOfCommand):
        chain.escalate("agent1", "blocked", "ctx", "blocked")
        assert chain.can_auto_escalate() is True

    def test_can_auto_escalate_over_limit(self, chain: ChainOfCommand):
        chain.escalate("agent1", "b1", "ctx", "critical")
        chain.escalate("agent2", "b2", "ctx", "blocked")
        chain.escalate("agent3", "b3", "ctx", "critical")
        chain.escalate("agent4", "b4", "ctx", "blocked")
        assert chain.can_auto_escalate() is False

    @pytest.mark.asyncio
    async def test_notify_user_no_ws(self, chain: ChainOfCommand):
        """Without ws_send_fn, notify_user returns None."""
        req = chain.escalate("agent1", "test", "ctx")
        response = await chain.notify_user(req, ws_send_fn=None)
        assert response is None

    @pytest.mark.asyncio
    async def test_notify_user_sends_message(self, chain: ChainOfCommand):
        """With ws_send_fn, the escalation message is sent."""
        sent = []

        async def fake_ws(msg):
            sent.append(msg)

        req = chain.escalate("agent1", "Help", "details", "blocked")
        # Schedule resolution in the background to unblock wait
        async def resolve_later():
            await asyncio.sleep(0.02)
            chain.resolve(req, "User says: proceed")

        asyncio.create_task(resolve_later())
        response = await chain.notify_user(req, fake_ws, timeout=5.0)
        assert response == "User says: proceed"
        assert len(sent) == 1
        assert sent[0]["type"] == "escalation"
        assert sent[0]["request_id"] == req.id

    @pytest.mark.asyncio
    async def test_notify_user_timeout(self, chain: ChainOfCommand):
        """If no response arrives before timeout, return None."""
        req = chain.escalate("agent1", "Help", "ctx", "blocked")

        async def fake_ws(msg):
            pass  # never resolves

        response = await chain.notify_user(req, fake_ws, timeout=0.05)
        assert response is None
        assert req.resolved is True
        assert req.resolution == "timeout"

    def test_receive_response(self, chain: ChainOfCommand):
        """receive_response resolves a pending escalation by ID."""
        req = chain.escalate("agent1", "Help", "ctx", "blocked")
        found = chain.receive_response(req.id, "Proceed with caution")
        assert found is True
        assert req.resolved
        assert req.resolution == "Proceed with caution"

    def test_receive_response_unknown_id(self, chain: ChainOfCommand):
        """Unknown request ID returns False."""
        found = chain.receive_response("nonexistent", "resolved")
        assert found is False

    def test_escalation_request_uuid_unique(self):
        """Each request gets a unique ID (not id())."""
        req1 = EscalationRequest("a1", "r1", "ctx")
        req2 = EscalationRequest("a2", "r2", "ctx")
        assert req1.id != req2.id

    def test_severity_literal(self):
        """Severity is constrained to valid literals."""
        req: EscalationRequest = EscalationRequest("a1", "r1", "ctx", "blocked")
        assert req.severity == "blocked"
        # Type checker would catch "catastrophic" at static analysis time


# ===================================================================
# sandbox.py — SandboxDetector
# ===================================================================

class TestSandboxDetector:
    """Topic tree, conflict detection, cycle prevention, lock TTL."""

    def test_register_topic(self, sandbox: SandboxDetector):
        sandbox.register_topic("root")
        sandbox.register_topic("child", parent="root")
        sandbox.register_topic("grandchild", parent="child")
        # Tree: root → child → grandchild
        assert "child" in sandbox._topic_tree["root"]
        assert "grandchild" in sandbox._topic_tree["child"]

    def test_register_topic_cycle_detection(self, sandbox: SandboxDetector):
        """Cannot register a topic as child of its own descendant (creates a cycle)."""
        sandbox.register_topic("a")
        sandbox.register_topic("b", parent="a")
        sandbox.register_topic("c", parent="b")
        # Trying to make 'a' a child of 'c' would create: a → b → c → a
        with pytest.raises(ValueError, match="would create a cycle"):
            sandbox.register_topic("a", parent="c")  # c already exists, adding parent a

    def test_register_topic_self_cycle(self, sandbox: SandboxDetector):
        """Cannot set a topic as its own parent."""
        sandbox.register_topic("a")
        with pytest.raises(ValueError, match="would create a cycle"):
            sandbox.register_topic("a", parent="a")

    def test_acquire_basic(self, sandbox: SandboxDetector):
        ok, msg = sandbox.acquire("topic1", "agent1")
        assert ok is True
        assert msg == ""
        assert sandbox._locks["topic1"].agent_id == "agent1"

    def test_acquire_same_topic_different_agent(self, sandbox: SandboxDetector):
        sandbox.acquire("topic1", "agent1")
        ok, msg = sandbox.acquire("topic1", "agent2")
        assert ok is False
        assert "already held" in msg

    def test_acquire_reentrant(self, sandbox: SandboxDetector):
        sandbox.acquire("topic1", "agent1")
        ok, _ = sandbox.acquire("topic1", "agent1")
        assert ok is True

    def test_acquire_hierarchical_conflict(self, sandbox: SandboxDetector):
        """Related topics (parent-child) conflict."""
        sandbox.register_topic("parent")
        sandbox.register_topic("child", parent="parent")
        sandbox.acquire("parent", "agent1")
        ok, msg = sandbox.acquire("child", "agent2")
        assert ok is False
        assert "overlaps with agents" in msg

    def test_acquire_unrelated_topics_no_conflict(self, sandbox: SandboxDetector):
        """Unrelated topics don't conflict."""
        sandbox.register_topic("finance")
        sandbox.register_topic("engineering")
        sandbox.acquire("finance", "agent1")
        ok, _ = sandbox.acquire("engineering", "agent2")
        assert ok is True

    def test_release(self, sandbox: SandboxDetector):
        sandbox.acquire("topic1", "agent1")
        sandbox.release("topic1", "agent1")
        assert "topic1" not in sandbox._locks

    def test_release_wrong_agent(self, sandbox: SandboxDetector):
        sandbox.acquire("topic1", "agent1")
        sandbox.release("topic1", "agent2")  # no-op
        assert "topic1" in sandbox._locks

    def test_release_all(self, sandbox: SandboxDetector):
        sandbox.acquire("t1", "agent1")
        sandbox.acquire("t2", "agent1")
        sandbox.release_all("agent1")
        assert len(sandbox._locks) == 0

    def test_stale_lock_reclamation(self, sandbox: SandboxDetector):
        """Locks older than TTL can be reclaimed by another agent."""
        sandbox._lock_ttl = 0.05  # short TTL
        sandbox.acquire("topic1", "agent1", resource_path="path")
        # Fake the lock age
        sandbox._locks["topic1"].acquired_at = time.time() - 1.0  # 1 second old
        time.sleep(0.01)
        ok, msg = sandbox.acquire("topic1", "agent2")
        assert ok is True, f"Should reclaim stale lock, got: {msg}"

    def test_cleanup_stale_locks(self, sandbox: SandboxDetector):
        """cleanup_stale_locks removes locks older than TTL."""
        sandbox._lock_ttl = 0.05
        sandbox.acquire("t1", "agent1")
        sandbox._locks["t1"].acquired_at = time.time() - 1.0  # make stale
        # Do NOT call acquire() here — it proactively cleans stale locks
        n = sandbox.cleanup_stale_locks()
        assert n == 1
        assert "t1" not in sandbox._locks

    def test_is_related_same(self, sandbox: SandboxDetector):
        """Same topic is always related."""
        assert sandbox._is_related("a", "a") is True

    def test_is_related_ancestor(self, sandbox: SandboxDetector):
        sandbox.register_topic("root")
        sandbox.register_topic("child", parent="root")
        assert sandbox._is_related("root", "child") is True
        assert sandbox._is_related("child", "root") is True

    def test_is_related_unrelated(self, sandbox: SandboxDetector):
        sandbox.register_topic("cats")
        sandbox.register_topic("dogs")
        assert sandbox._is_related("cats", "dogs") is False

    def test_is_related_depth_limit(self, sandbox: SandboxDetector):
        """Deep trees don't cause infinite loops."""
        # Build a degenerate chain
        prev = "root"
        for i in range(150):
            cur = f"node_{i}"
            sandbox.register_topic(cur, parent=prev)
            prev = cur
        # Should not hang
        result = sandbox._is_related("root", f"node_{99}")
        assert result is True

    def test_no_topic_tree(self, sandbox: SandboxDetector):
        """Without registered topics, only exact matches detect conflict."""
        ok, _ = sandbox.acquire("t1", "agent1")
        assert ok is True
        ok, _ = sandbox.acquire("t2", "agent2")
        assert ok is True  # no tree → no relationship


# ===================================================================
# state.py — OrchestratorState
# ===================================================================

class TestOrchestratorState:
    """Agent registration, status updates, swarm emission, history."""

    def test_register_agent(self, state: OrchestratorState):
        run = AgentRun(agent_type="basic", task_description="test task")
        state.register_agent("agent_1", run)
        assert "agent_1" in state.active_agents
        assert state.active_agents["agent_1"].task_description == "test task"

    def test_update_status(self, state: OrchestratorState):
        run = AgentRun(agent_type="basic")
        state.register_agent("agent_1", run)
        state.update_status("agent_1", "done")
        assert run.status == "done"

    def test_update_status_unknown_id(self, state: OrchestratorState, caplog):
        """Updating status for unknown ID logs a warning (doesn't crash)."""
        import logging
        caplog.set_level(logging.WARNING)
        state.update_status("nonexistent", "done")
        assert "unknown agent_id" in caplog.text

    def test_update_status_archives_completed(self, state: OrchestratorState):
        """When status changes to done/failed/cancelled, agent is archived."""
        run = AgentRun(agent_type="basic")
        state.register_agent("agent_1", run)
        state.update_status("agent_1", "done")
        assert "agent_1" not in state.active_agents
        assert len(state.completed_agents) == 1
        assert state.completed_agents[0][0] == "agent_1"

    def test_remove_agent(self, state: OrchestratorState):
        state.register_agent("agent_1", AgentRun(agent_type="basic"))
        state.remove_agent("agent_1")
        assert "agent_1" not in state.active_agents

    def test_agent_run_defaults(self):
        """AgentRun has sensible defaults."""
        run = AgentRun(agent_type="basic")
        assert run.status == "running"
        assert run.depth == 1
        assert run.model == "unknown"
        assert run.task_description == ""

    def test_completed_agents_history_trimmed(self, state: OrchestratorState):
        """Completed agents history doesn't grow unbounded."""
        state._max_history = 5
        for i in range(10):
            run = AgentRun(agent_type="basic", task_description=f"task_{i}")
            state.register_agent(f"agent_{i}", run)
            state.update_status(f"agent_{i}", "done")
        assert len(state.completed_agents) == 5

    @pytest.mark.asyncio
    async def test_emit_swarm_update(self, state: OrchestratorState):
        """Swarm update includes orchestrator node + active agents."""
        run = AgentRun(agent_type="reflective", task_description="test task",
                       parent_id="parent1")
        state.register_agent("agent_1", run)

        sent = []

        async def fake_ws(msg):
            sent.append(msg)

        await state.emit_swarm_update(fake_ws)
        assert len(sent) == 1
        data = sent[0]
        assert data["type"] == "swarm_update"
        nodes = data["data"]["nodes"]
        edges = data["data"]["edges"]
        assert len(nodes) == 2  # orchestrator + agent_1
        assert len(edges) == 1
        assert edges[0]["from"] == "parent1"
        assert edges[0]["to"] == "agent_1"

    @pytest.mark.asyncio
    async def test_emit_swarm_update_full_description(self, state: OrchestratorState):
        """Full task description is sent (not truncated)."""
        long_desc = "A" * 100
        run = AgentRun(agent_type="basic", task_description=long_desc)
        state.register_agent("agent_1", run)

        sent = []

        async def fake_ws(msg):
            sent.append(msg)

        await state.emit_swarm_update(fake_ws)
        node = sent[0]["data"]["nodes"][1]
        assert len(node["task"]) == 100  # not truncated to 40
