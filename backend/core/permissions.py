"""
Permission gating for all tool calls and agent actions.
Source: Brain dump ("like opencode") — compact inline confirmation before write/exec.

Three modes (set in data/settings.json -> permissions.mode):
  "ask"        — confirm every NORMAL+ action individually
  "auto-safe"  — auto-allow SAFE, confirm ELEVATED+
  "allow-all"  — allow everything, log everything

Four tiers:
  SAFE      — read-only, no external side effects -> always auto-approved
  NORMAL    — network reads, file reads          -> confirm in "ask" mode
  ELEVATED  — file writes, process spawn         -> confirm in "ask" + "auto-safe"
  DANGEROUS — system commands, credential access -> always confirm
"""
import asyncio
import logging
from enum import Enum
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class PermTier(Enum):
    SAFE = 0
    NORMAL = 1
    ELEVATED = 2
    DANGEROUS = 3


# Which tier each tool belongs to
TOOL_TIERS: dict[str, PermTier] = {
    # SAFE — read only
    "vault_read":       PermTier.SAFE,
    "memory_read":      PermTier.SAFE,
    "list_files":       PermTier.SAFE,
    "web_search":       PermTier.SAFE,
    # NORMAL — reads with external contact
    "url_fetch":        PermTier.NORMAL,
    "read_file":        PermTier.NORMAL,
    "system_info":      PermTier.NORMAL,
    # ELEVATED — writes and spawns
    "write_file":       PermTier.ELEVATED,
    "edit_file":        PermTier.ELEVATED,
    "vault_write":      PermTier.ELEVATED,
    "memory_write":     PermTier.ELEVATED,
    "screenshot":       PermTier.ELEVATED,
    # DANGEROUS — system-level
    "shell":            PermTier.DANGEROUS,
    "run_code":         PermTier.DANGEROUS,
    "delete_file":      PermTier.DANGEROUS,
}


class PermissionGate:
    """
    Instantiate once per session. Maintains session-level "always allow" decisions.
    """

    def __init__(
        self,
        mode: str,  # "ask" | "auto-safe" | "allow-all"
        ask_fn: Callable[[str], Awaitable[bool]],
    ):
        self.mode = mode
        self.ask_fn = ask_fn
        self._session_always_allow: set[str] = set()

    async def check(self, tool_name: str, tool_input: dict = None) -> bool:
        """
        Returns True if the tool call should proceed.
        Returns False if denied (caller must NOT execute the tool).
        """
        tier = TOOL_TIERS.get(tool_name, PermTier.ELEVATED)  # unknown = elevated

        # Always allow SAFE
        if tier == PermTier.SAFE:
            return True

        # Check session-level always-allow
        if tool_name in self._session_always_allow:
            return True

        # Determine if we need to ask
        needs_ask = (
            self.mode == "ask" and tier.value >= PermTier.NORMAL.value
        ) or (
            self.mode == "auto-safe" and tier.value >= PermTier.ELEVATED.value
        ) or (
            tier == PermTier.DANGEROUS  # always ask for DANGEROUS
        )

        if self.mode == "allow-all" and tier != PermTier.DANGEROUS:
            logger.info(f"[perm] auto-allow ({self.mode}): {tool_name}")
            return True

        if needs_ask:
            input_preview = ""
            if tool_input:
                key = list(tool_input.keys())[0] if tool_input else ""
                val = str(list(tool_input.values())[0])[:60] if tool_input else ""
                input_preview = f" ({key}={val!r})"

            prompt = (
                f"Allow {tool_name}{input_preview}? "
                f"[tier: {tier.name}] - y/n/always: "
            )
            response = await self.ask_fn(prompt)
            if isinstance(response, str):
                if response.lower() in ("always", "a"):
                    self._session_always_allow.add(tool_name)
                    return True
                return response.lower() in ("y", "yes")
            return bool(response)

        return True
