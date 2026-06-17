"""
Orchestrator engine — full plan/task lifecycle, sub-agent router, plan mode.
Wires OrchestratorState with task queue, plan decomposition, and sub-agent dispatch.
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Coroutine

from backend.core.orchestrator.state import OrchestratorState, AgentRun

logger = logging.getLogger(__name__)


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


@dataclass
class Plan:
    """A complete plan with multiple steps."""
    id: str
    name: str
    steps: list[PlanStep] = field(default_factory=list)
    created_at: float = 0.0
    status: str = "active"  # active | paused | completed | failed


class Orchestrator:
    """Coordinates multiple sub-agents to execute complex plans."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.state = OrchestratorState(config)
        self.plans: dict[str, Plan] = {}
        self._ws_send_fn: Callable | None = None
        self._loop = asyncio.get_event_loop()

    def set_ws_sender(self, fn: Callable[[dict], Coroutine[Any, Any, None]]):
        """Set the WebSocket send function for swarm UI updates."""
        self._ws_send_fn = fn

    # ── Plan Management ──────────────────────────────────────────────

    def create_plan(self, name: str, steps: list[dict]) -> Plan:
        """Create a new plan from a list of step descriptors."""
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        plan = Plan(
            id=plan_id,
            name=name,
            steps=[
                PlanStep(
                    id=f"{plan_id}_step_{i}",
                    description=s.get("description", ""),
                    agent_type=s.get("agent_type", "basic"),
                    depends_on=s.get("depends_on", []),
                )
                for i, s in enumerate(steps)
            ],
            created_at=time.time(),
        )
        self.plans[plan_id] = plan
        logger.info(f"Created plan {plan_id}: {name} ({len(steps)} steps)")
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
        logger.info(f"Cancelled plan {plan_id}")

    # ── Task Router ─────────────────────────────────────────────────

    def get_runnable_steps(self, plan_id: str) -> list[PlanStep]:
        """Return all steps whose dependencies are satisfied."""
        plan = self.plans.get(plan_id)
        if not plan or plan.status != "active":
            return []
        runnable = []
        for step in plan.steps:
            if step.status != "pending":
                continue
            deps_met = all(
                next((s for s in plan.steps if s.id == dep_id), None)
                and next((s for s in plan.steps if s.id == dep_id), None).status == "done"
                for dep_id in step.depends_on
            )
            if deps_met:
                runnable.append(step)
        return runnable

    async def dispatch_step(self, plan_id: str, step: PlanStep,
                            agent_factory: Callable) -> str:
        """Dispatch a single plan step to a sub-agent."""
        agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        step.status = "running"
        step.agent_id = agent_id

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
            agent = agent_factory(agent_type=step.agent_type)
            result = ""
            async for chunk in agent.handle_user_input(step.description):
                if isinstance(chunk, str):
                    result += chunk
            step.result = result
            step.status = "done"
            self.state.update_status(agent_id, "done")
            logger.info(f"Step {step.id} completed")
        except Exception as e:
            step.status = "failed"
            step.result = f"Error: {e}"
            self.state.update_status(agent_id, "failed")
            logger.error(f"Step {step.id} failed: {e}")

        if self._ws_send_fn:
            await self.state.emit_swarm_update(self._ws_send_fn)

        return step.result

    async def execute_plan(self, plan_id: str, agent_factory: Callable,
                           max_concurrent: int = 3) -> dict:
        """Execute a plan step by step, respecting dependencies."""
        plan = self.plans.get(plan_id)
        if not plan:
            return {"status": "error", "message": "Plan not found"}

        semaphore = asyncio.Semaphore(max_concurrent)
        results = {}

        async def _run_step(step: PlanStep):
            async with semaphore:
                result = await self.dispatch_step(plan_id, step, agent_factory)
                results[step.id] = result

        while True:
            runnable = self.get_runnable_steps(plan_id)
            if not runnable:
                break
            tasks = [asyncio.create_task(_run_step(s)) for s in runnable]
            await asyncio.gather(*tasks, return_exceptions=True)

        all_done = all(s.status == "done" for s in plan.steps)
        plan.status = "completed" if all_done else "failed"
        return {
            "status": plan.status,
            "plan_id": plan_id,
            "results": results,
        }
