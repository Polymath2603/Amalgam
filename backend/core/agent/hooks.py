"""Pre/post event hook system for tools.

Hooks are callables that are invoked before or after tool execution.
They can modify arguments, cancel execution, or react to results.

Hook signature:
    async def hook(tool_name: str, tool_args: dict, context: dict) -> Optional[dict]:
        # context contains: session_id, user_message, permission_level
        # Return None to allow, or a dict with {"error": "reason"} to block
"""

import logging
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

HookFunc = Callable[[str, dict, dict], Coroutine[Any, Any, Optional[dict]]]


class ToolHooks:
    """Registry of pre/post hooks for tool execution.

    Hooks are stored in a dict keyed by a unique ID for O(1) removal,
    sorted by priority for ordered execution.
    """

    def __init__(self):
        self._pre_hooks: dict[int, tuple[HookFunc, int]] = {}   # id -> (hook, priority)
        self._post_hooks: dict[int, tuple[HookFunc, int]] = {}
        self._next_id = 0

    def register_pre(self, hook: HookFunc, priority: int = 10) -> int:
        """Register a pre-execution hook with optional priority (lower runs first)."""
        hook_id = self._next_id
        self._next_id += 1
        self._pre_hooks[hook_id] = (hook, priority)
        return hook_id

    def register_post(self, hook: HookFunc, priority: int = 10) -> int:
        """Register a post-execution hook with optional priority (lower runs first)."""
        hook_id = self._next_id
        self._next_id += 1
        self._post_hooks[hook_id] = (hook, priority)
        return hook_id

    def unregister_pre(self, hook_or_id) -> None:
        """Remove a pre-execution hook by id or function reference."""
        if isinstance(hook_or_id, int):
            self._pre_hooks.pop(hook_or_id, None)
        else:
            to_remove = [k for k, (h, _) in self._pre_hooks.items() if h is hook_or_id]
            for k in to_remove:
                del self._pre_hooks[k]

    def unregister_post(self, hook_or_id) -> None:
        """Remove a post-execution hook by id or function reference."""
        if isinstance(hook_or_id, int):
            self._post_hooks.pop(hook_or_id, None)
        else:
            to_remove = [k for k, (h, _) in self._post_hooks.items() if h is hook_or_id]
            for k in to_remove:
                del self._post_hooks[k]

    async def run_pre(self, tool_name: str, tool_args: dict,
                      context: dict) -> Optional[dict]:
        """Run all pre-hooks sorted by priority.

        Runs every hook and collects errors rather than returning early.
        Returns the first error dict, or None to proceed.
        """
        sorted_hooks = sorted(self._pre_hooks.values(), key=lambda x: x[1])
        errors: list[str] = []
        for hook, priority in sorted_hooks:
            try:
                result = await hook(tool_name, tool_args, context)
                if result is not None and "error" in result:
                    errors.append(str(result["error"]))
            except Exception as e:
                logger.warning("Pre-hook error for %s: %s", tool_name, e)
                errors.append(f"Pre-hook error: {e}")
        if errors:
            return {"error": "; ".join(errors)}
        return None

    async def run_post(self, tool_name: str, tool_args: dict,
                       context: dict) -> None:
        """Run all post-hooks sorted by priority (fire-and-forget, errors logged)."""
        sorted_hooks = sorted(self._post_hooks.values(), key=lambda x: x[1])
        for hook, priority in sorted_hooks:
            try:
                await hook(tool_name, tool_args, context)
            except Exception as e:
                logger.warning("Post-hook error for %s: %s", tool_name, e)

    def clear(self):
        """Remove all hooks."""
        self._pre_hooks.clear()
        self._post_hooks.clear()
