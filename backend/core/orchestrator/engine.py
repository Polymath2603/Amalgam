"""Orchestrator engine — full plan/task lifecycle, sub-agent router, plan mode.
Wires OrchestratorState with task queue, plan decomposition, and sub-agent dispatch.
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Coroutine, Protocol, runtime_checkable

from backend.core.orchestrator.state import OrchestratorState, AgentRun

logger = logging.getLogger(__name__)


@runtime_checkable
class AgentProtocol(Protocol):
    """Formal protocol for sub-agents used by the orchestrator.

    Any agent type passed to ``dispatch_step`` must conform to this interface.
    """

    async def handle_user_input(self, input: str) -> AsyncGenerator[str, None]:
        """Process a task description and yield result chunks."""
        ...


@dataclass
class PlanStep:
    """A single step in a multi-agent plan."""
    id: str
    description: str
    agent_type: str = "basic"
    status: str = "pending"  # pending | running | done | failed | blocked
    depends_on: list[str] = field(default_factory=list)
    result: str = ""
    agent_id: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "agent_type": self.agent_type,
            "status": self.status,
            "depends_on": list(self.depends_on),
            "result": self.result,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanStep":
        return cls(
            id=data["id"],
            description=data.get("description", ""),
            agent_type=data.get("agent_type", "basic"),
            status=data.get("status", "pending"),
            depends_on=data.get("depends_on", []),
            result=data.get("result", ""),
            agent_id=data.get("agent_id", ""),
        )


@dataclass
class Plan:
    """A complete plan with multiple steps."""
    id: str
    name: str
    steps: list[PlanStep] = field(default_factory=list)
    created_at: float = 0.0
    status: str = "active"  # active | paused | completed | failed

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            steps=[PlanStep.from_dict(s) for s in data.get("steps", [])],
            created_at=data.get("created_at", 0.0),
            status=data.get("status", "active"),
        )


class Orchestrator:
    """Coordinates multiple sub-agents to execute complex plans."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.state = OrchestratorState(config)
        self.plans: dict[str, Plan] = {}
        self._ws_send_fn: Callable | None = None
        # Lazily resolve the loop on first use instead of capturing at init.
        self._loop: asyncio.AbstractEventLoop | None = None
        # Restore persisted state (plans, agent runs) from disk
        self.load_state()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop — create a new one for synchronous callers
                self._loop = asyncio.new_event_loop()
        return self._loop

    def set_ws_sender(self, fn: Callable[[dict], Coroutine[Any, Any, None]]):
        """Set the WebSocket send function for swarm UI updates."""
        self._ws_send_fn = fn

    # ── Persistence ─────────────────────────────────────────────────

    def _state_path(self) -> Path:
        return Path(self.config.get("orchestrator.state_path", "data/orchestrator_state.json"))

    def save_state(self):
        """Persist plans and agent state to disk as JSON."""
        path = self._state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "plans": {pid: plan.to_dict() for pid, plan in self.plans.items()},
                "state": self.state.to_dict(),
            }
            path.write_text(json.dumps(data, indent=2, default=str))
            logger.debug("Orchestrator state saved to %s", path)
        except Exception:
            logger.exception("Failed to save orchestrator state")

    def load_state(self):
        """Restore plans and agent state from disk."""
        path = self._state_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            plans = {
                pid: Plan.from_dict(pdata)
                for pid, pdata in data.get("plans", {}).items()
            }
            new_state = OrchestratorState.from_dict(
                data.get("state", {}), config=self.config,
            )
            # Assign only after successful construction
            self.plans = plans
            self.state = new_state
            logger.info("Orchestrator state loaded from %s (%d plans)", path, len(self.plans))
        except Exception:
            logger.exception("Failed to load orchestrator state; starting fresh")

    # ── Plan Management ──────────────────────────────────────────────

    _REQUIRED_STEP_FIELDS = frozenset({"description"})

    def create_plan(self, name: str, steps: list[dict]) -> Plan:
        """Create a new plan from a list of step descriptors."""
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"

        parsed: list[PlanStep] = []
        for i, s in enumerate(steps):
            missing = self._REQUIRED_STEP_FIELDS - s.keys()
            if missing:
                logger.warning(
                    "Step %d in plan %r missing required fields: %s",
                    i, name, sorted(missing),
                )
            parsed.append(
                PlanStep(
                    id=f"{plan_id}_step_{i}",
                    description=s.get("description", ""),
                    agent_type=s.get("agent_type", "basic"),
                    depends_on=s.get("depends_on", []),
                )
            )

        plan = Plan(
            id=plan_id,
            name=name,
            steps=parsed,
            created_at=time.time(),
        )
        self.plans[plan_id] = plan
        logger.info("Created plan %s: %s (%d steps)", plan_id, name, len(steps))
        return plan

    def get_plan(self, plan_id: str) -> Plan | None:
        return self.plans.get(plan_id)

    def cancel_plan(self, plan_id: str):
        """Cancel a plan and all its running sub-agents."""
        plan = self.plans.get(plan_id)
        if not plan:
            return
        plan.status = "failed"
        for step in plan.steps:
            if step.status == "running" and step.agent_id:
                self.state.update_status(step.agent_id, "cancelled")
            step.status = "failed"
        logger.info("Cancelled plan %s", plan_id)

    # ── Task Router ─────────────────────────────────────────────────

    def get_runnable_steps(self, plan_id: str) -> list[PlanStep]:
        """Return all steps whose dependencies are satisfied.

        Uses an O(1) step-id index to avoid repeated linear scans.
        """
        plan = self.plans.get(plan_id)
        if not plan or plan.status != "active":
            return []

        # Build O(1) status lookup — resolves the O(n²·d) issue
        step_status: dict[str, str] = {s.id: s.status for s in plan.steps}

        runnable: list[PlanStep] = []
        for step in plan.steps:
            if step.status != "pending":
                continue
            # Each dependency is a single dict lookup instead of two O(n) scans
            deps_met = all(
                step_status.get(dep_id) == "done"
                for dep_id in step.depends_on
            )
            if deps_met:
                runnable.append(step)
        return runnable

    async def dispatch_step(
        self,
        plan_id: str,
        step: PlanStep,
        agent_factory: Callable[[str], AgentProtocol],
    ) -> str:
        """Dispatch a single plan step to a sub-agent.

        ``agent_factory`` must return an object conforming to :class:`AgentProtocol`.
        """
        agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        step.status = "running"
        step.agent_id = agent_id

        try:
            agent = agent_factory(agent_type=step.agent_type)
        except Exception as e:
            step.status = "failed"
            step.result = f"Error creating agent: {e}"
            logger.error("Step %s agent creation failed: %s", step.id, e)
            return step.result

        run = AgentRun(
            agent_type=step.agent_type,
            status="running",
            depth=1,
            task_description=step.description,
            model=self.config.get("model", "unknown"),
            parent_id="orchestrator",
        )
        self.state.register_agent(agent_id, run)

        if self._ws_send_fn:
            await self.state.emit_swarm_update(self._ws_send_fn)

        try:
            result = ""
            async for chunk in agent.handle_user_input(step.description):
                if isinstance(chunk, str):
                    result += chunk
            step.result = result
            step.status = "done"
            self.state.update_status(agent_id, "done")
            logger.info("Step %s completed", step.id)
        except asyncio.CancelledError:
            step.status = "failed"
            step.result = "Step was cancelled"
            self.state.update_status(agent_id, "failed")
            logger.warning("Step %s was cancelled", step.id)
            raise  # Propagate CancelledError
        except Exception as e:
            step.status = "failed"
            step.result = f"Error: {e}"
            self.state.update_status(agent_id, "failed")
            logger.error("Step %s failed: %s", step.id, e)

        if self._ws_send_fn:
            await self.state.emit_swarm_update(self._ws_send_fn)

        return step.result

    async def execute_plan(
        self,
        plan_id: str,
        agent_factory: Callable[[str], AgentProtocol],
        max_concurrent: int | None = None,
    ) -> dict:
        """Execute a plan step by step, respecting dependencies.

        Parameters
        ----------
        plan_id:
            The plan to execute.
        agent_factory:
            Factory callable that receives ``agent_type`` and returns an
            :class:`AgentProtocol`-compatible object.
        max_concurrent:
            Maximum number of steps to run in parallel.  Falls back to the
            per-plan configuration or 3 if not set anywhere.
        """
        plan = self.plans.get(plan_id)
        if not plan:
            return {"status": "error", "message": "Plan not found"}

        # Resolve concurrency limit:  per-call > per-plan config > default
        effective_max = (
            max_concurrent
            or self.config.get("max_concurrent_steps")
            or 3
        )
        semaphore = asyncio.Semaphore(effective_max)
        results: dict[str, str] = {}

        async def _run_step(step: PlanStep) -> None:
            async with semaphore:
                result = await self.dispatch_step(plan_id, step, agent_factory)
                results[step.id] = result

        while True:
            runnable = self.get_runnable_steps(plan_id)
            if not runnable:
                break
            tasks = [asyncio.create_task(_run_step(s)) for s in runnable]
            if not tasks:
                break
            # Wait for ALL tasks to complete (not just the first exception),
            # preventing orphaned tasks that would be left running in the
            # background when FIRST_EXCEPTION returns early.
            done_set, pending = await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
            if pending:
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            for t in done_set:
                exc = t.exception()
                if exc is not None and not isinstance(exc, asyncio.CancelledError):
                    logger.error("Step task failed with %s: %s", type(exc).__name__, exc)

        all_done = all(s.status == "done" for s in plan.steps)
        plan.status = "completed" if all_done else "failed"
        return {
            "status": plan.status,
            "plan_id": plan_id,
            "results": results,
        }
