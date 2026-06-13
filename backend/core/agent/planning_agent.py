"""
PlanningAgent — decomposes complex requests into steps and executes them.

Two-tier routing:
- Simple tasks (Q&A, single-tool) → fast-path via BasicAgent
- Compound tasks → LLM decomposition → sequential execution → synthesis
"""

import json
import logging
from typing import Any, AsyncIterator, Optional

from backend.core.agent.base import BaseAgent
from backend.core.agent.basic_agent import BasicAgent

logger = logging.getLogger(__name__)


# Prefixes that indicate a simple lookup — no planning needed
_SIMPLE_PREFIXES = [
    "what is", "what are", "who is", "when is",
    "where is", "how much", "tell me about",
    "define", "what does",
]


class PlanningAgent(BaseAgent):
    """
    Agent that decomposes complex tasks into steps and executes them sequentially.
    """

    def __init__(self, llm_router, memory, mcp_client=None,
                 settings=None, tools=None):
        super().__init__(
            llm_client=llm_router,
            tools=tools or {},
            memory=memory,
            config=settings or {},
        )
        self._inner = BasicAgent(llm_router, memory, mcp_client, settings, tools)

    async def run(self, user_message: str, context: dict) -> AsyncIterator[str]:
        """
        Run the planning agent for a user message.

        Yields text chunks including:
        - Plan description (if compound task)
        - Progress updates as each step completes
        - Final synthesized response
        """
        session_id = context.get("session_id", "unknown")

        # Step 1: Classify the task
        task_type = self._classify_task(user_message)

        if task_type == "simple":
            # Simple tasks don't need planning — fast path
            logger.debug(f"Task classified as simple: {user_message[:50]}")
            async for chunk in self._inner.run(user_message, context):
                yield chunk
            return

        # Step 2: Decompose compound task into steps
        yield "[Planning] Breaking down your request...\n\n"

        steps = await self._decompose_task(user_message, context)

        if not steps:
            # Decomposition failed — fall back to basic agent
            logger.warning("Task decomposition returned no steps — falling back to basic agent")
            async for chunk in self._inner.run(user_message, context):
                yield chunk
            return

        # Step 3: Execute each step
        step_results: list[dict] = []
        for i, step in enumerate(steps):
            desc = step.get("description", f"Step {i+1}")
            yield f"\n**{desc}:**\n\n"

            try:
                result = await self._execute_step(
                    step, i + 1, steps, user_message, context
                )
                step_results.append({
                    "step": i + 1,
                    "description": desc,
                    "result": result,
                })
                yield result
            except Exception as e:
                err = f"[Error in step {i+1}: {e}]"
                step_results.append({
                    "step": i + 1,
                    "description": desc,
                    "result": err,
                })
                yield err
                logger.exception(f"PlanningAgent step {i+1} failed")

        # Step 4: Synthesize final response
        yield "\n\n**[Synthesizing final response...]**\n\n"
        async for chunk in self._synthesize(user_message, step_results, context):
            yield chunk

    async def handle_user_input(self, text: str, images: list = None,
                                relationship_context: str = "") -> Any:
        """Legacy interface — delegates to run()."""
        ctx = {"session_id": "", "relationship_context": relationship_context or ""}
        async for chunk in self.run(text, ctx):
            yield chunk

    async def get_response(self, text: str) -> str:
        """Delegate to inner agent."""
        return await self._inner.get_response(text)

    def load_history(self, session_id: str):
        self._inner.load_history(session_id)

    # --- Internal ---

    @staticmethod
    def _classify_task(user_message: str) -> str:
        """Classify as 'simple' or 'compound' based on heuristics."""
        msg_lower = user_message.lower().strip()

        # Simple Q&A patterns
        for prefix in _SIMPLE_PREFIXES:
            if msg_lower.startswith(prefix):
                return "simple"

        # Tool-triggering keywords — simple (single tool call)
        simple_tool_keywords = [
            "search", "look up", "find", "calculate",
            "translate", "summarize", "remind me",
        ]
        for kw in simple_tool_keywords:
            if kw in msg_lower:
                return "simple"

        # Multi-request patterns — compound
        compound_markers = [
            " and also ", " then ", " after that ",
            "first ", "next,", "finally,", "compare",
            "analyze", "research", "investigate",
        ]
        for marker in compound_markers:
            if marker in msg_lower:
                return "compound"

        # Requests with 3+ sentences are likely compound
        sentences = [s for s in msg_lower.split(".") if s.strip()]
        if len(sentences) >= 3:
            return "compound"

        # Default: let the LLM decide
        return "compound"

    async def _decompose_task(self, user_message: str, context: dict) -> list[dict]:
        """Use the LLM to break a compound request into ordered steps."""
        prompt = f"""Decompose the user's request into a sequence of up to 5 steps.

Each step should be:
1. Independent enough to execute on its own
2. A clear action description (not a question)
3. Ordered logically (earlier steps feed later steps)

User request: {user_message}

Respond with a JSON array of objects:
[
  {{"description": "Clear action description for step 1"}},
  {{"description": "Clear action description for step 2"}}
]

If the request is simple enough for a single step, return a single-element array.
Respond ONLY with valid JSON, no explanation, no markdown."""

        try:
            response = await self.llm.generate(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            response = response.strip()
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
            steps = json.loads(response)

            if isinstance(steps, list) and len(steps) > 0:
                return steps[:5]  # cap at 5 steps
            return []
        except Exception as e:
            logger.warning(f"Task decomposition failed: {e}")
            return []

    async def _execute_step(
        self,
        step: dict,
        step_num: int,
        all_steps: list[dict],
        original_request: str,
        context: dict,
    ) -> str:
        """Execute a single step using BasicAgent."""
        step_instruction = step.get("description", "")
        step_context = dict(context)

        # Include prior steps' results for context
        if step_num > 1:
            prior_text = "\n".join(
                f"Step {s['step']}: {s['result'][:500]}"
                for s in all_steps[:step_num - 1]
            )
            full_instruction = f"{step_instruction}\n\n[Context from prior steps:\n{prior_text}]"
        else:
            full_instruction = step_instruction

        result_chunks = []
        async for chunk in self._inner.run(full_instruction, step_context):
            result_chunks.append(chunk)

        return "".join(result_chunks)

    async def _synthesize(
        self,
        original_request: str,
        step_results: list[dict],
        context: dict,
    ) -> AsyncIterator[str]:
        """Combine all step results into a coherent final response."""
        results_text = "\n\n".join(
            f"Step {r['step']} — {r['description']}:\n{r['result']}"
            for r in step_results
        )

        synthesis_prompt = f"""The user asked: {original_request}

Here are the results from each step:
{results_text}

Write a clear, complete response that integrates all the above results.
Address the user's original request directly. Be concise — the user already
saw progress updates, so this is just the final summary."""

        async for chunk in self.llm.stream_complete(synthesis_prompt):
            yield chunk
