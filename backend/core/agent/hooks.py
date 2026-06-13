"""Pre/post event hook system for tools.

Hooks are callables that are invoked before or after tool execution.
They can modify arguments, cancel execution, or react to results.

Hook signature:
    async def hook(tool_name: str, tool_args: dict, context: dict) -> Optional[dict]:
        # context contains: session_id, user_message, permission_level
        # Return None to allow, or a dict with {"error": "reason"} to block
"""

import logging
import time
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

HookFunc = Callable[[str, dict, dict], Coroutine[Any, Any, Optional[dict]]]


class ToolHooks:
    """Registry of pre/post hooks for tool execution."""

    def __init__(self):
        self._pre_hooks: list[HookFunc] = []
        self._post_hooks: list[HookFunc] = []

    def register_pre(self, hook: HookFunc):
        """Register a pre-execution hook."""
        self._pre_hooks.append(hook)

    def register_post(self, hook: HookFunc):
        """Register a post-execution hook."""
        self._post_hooks.append(hook)

    def unregister_pre(self, hook: HookFunc):
        """Remove a pre-execution hook."""
        if hook in self._pre_hooks:
            self._pre_hooks.remove(hook)

    def unregister_post(self, hook: HookFunc):
        """Remove a post-execution hook."""
        if hook in self._post_hooks:
            self._post_hooks.remove(hook)

    async def run_pre(self, tool_name: str, tool_args: dict,
                      context: dict) -> Optional[dict]:
        """Run all pre-hooks. Returns first error dict, or None to proceed."""
        for hook in self._pre_hooks:
            try:
                result = await hook(tool_name, tool_args, context)
                if result is not None and "error" in result:
                    return result
            except Exception as e:
                logger.warning("Pre-hook error for %s: %s", tool_name, e)
                return {"error": f"Pre-hook error: {e}"}
        return None

    async def run_post(self, tool_name: str, tool_args: dict,
                       context: dict) -> None:
        """Run all post-hooks (fire-and-forget, errors logged)."""
        for hook in self._post_hooks:
            try:
                await hook(tool_name, tool_args, context)
            except Exception as e:
                logger.warning("Post-hook error for %s: %s", tool_name, e)

    def clear(self):
        """Remove all hooks."""
        self._pre_hooks.clear()
        self._post_hooks.clear()
