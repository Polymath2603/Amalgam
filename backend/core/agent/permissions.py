"""Tool permission system — categories of tool access per conversation.

Three permission levels (set in settings):
    "readonly" — only read-only tools allowed
    "confirm" — dangerous tools require user confirmation
    "full" — all tools allowed without confirmation

Plus a PermissionGate that wraps ToolPermissions with interactive user
confirmation (ask/auto-safe/allow-all modes with async ask_fn).

Used by:
  - MCPClient (directly uses ToolPermissions)
  - WebSocket handler (uses PermissionGate for interactive confirmation)
"""

import logging
from enum import Enum
from typing import Callable, Awaitable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Original simple permission level (used by MCPClient)
# ---------------------------------------------------------------------------

class PermissionLevel(str, Enum):
    READONLY = "readonly"
    CONFIRM = "confirm"
    FULL = "full"


# Default tool classifications
READONLY_TOOLS = {
    "read_file", "list_directory", "glob", "grep", "web_search",
    "web_fetch", "list_skills", "skill", "summarize_url",
    "get_system_info", "list_characters", "get_character_info",
    "get_settings", "get_memory_stats", "get_session_info",
    "memory_search", "vault_search",
}

CONFIRM_TOOLS = {
    "shell", "execute_command", "write_file", "edit_file",
    "create_file", "delete_file", "create_skill", "delete_skill",
    "reminder", "send_notification",
}

DANGEROUS_TOOLS = {
    "shell", "execute_command", "delete_file", "delete_skill",
}


class ToolPermissions:
    """Per-session tool permission state (simple mode)."""

    def __init__(self, level: PermissionLevel = PermissionLevel.FULL):
        self.level = level
        self._approved_once: set[str] = set()

    def check_tool_allowed(self, tool_name: str) -> tuple[bool, Optional[str]]:
        """Check if a tool is allowed at the current permission level.

        Returns (allowed, reason). reason is None if allowed.
        """
        if self.level == PermissionLevel.FULL:
            return True, None

        if tool_name in self._approved_once:
            return True, None

        if self.level == PermissionLevel.READONLY:
            if tool_name not in READONLY_TOOLS:
                return False, f"Tool '{tool_name}' requires higher permission level (current: readonly)"
            return True, None

        if self.level == PermissionLevel.CONFIRM:
            if tool_name in DANGEROUS_TOOLS:
                return False, f"Tool '{tool_name}' requires confirmation. Use /approve to allow."
            if tool_name in CONFIRM_TOOLS or tool_name not in READONLY_TOOLS:
                return False, f"Permission needed for '{tool_name}'. Use /approve to allow once."
            return True, None

        return True, None

    def approve_tool_once(self, tool_name: str):
        """Approve a tool for one-time use at confirm level."""
        self._approved_once.add(tool_name)

    def revoke_approval(self, tool_name: str):
        """Revoke one-time approval."""
        self._approved_once.discard(tool_name)

    def set_level(self, level: PermissionLevel):
        """Change the permission level."""
        self.level = level
        self._approved_once.clear()

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "approved_once": list(self._approved_once),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolPermissions":
        inst = cls(level=PermissionLevel(data.get("level", "full")))
        inst._approved_once = set(data.get("approved_once", []))
        return inst


# ---------------------------------------------------------------------------
# Enhanced PermissionGate with interactive confirmation (plan's Task 8 spec)
# ---------------------------------------------------------------------------

class PermTier(Enum):
    """Classification of a tool's potential impact level."""
    SAFE = 0       # read-only, no external side effects
    NORMAL = 1     # network reads, file reads
    ELEVATED = 2   # file writes, process spawn
    DANGEROUS = 3  # system commands, credential access


# Which tier each tool belongs to (maps tool names to PermTier)
TOOL_TIERS: dict[str, PermTier] = {
    # SAFE — read only
    "read_file":          PermTier.SAFE,
    "list_directory":     PermTier.SAFE,
    "glob":              PermTier.SAFE,
    "grep":              PermTier.SAFE,
    "vault_read":        PermTier.SAFE,
    "vault_search":      PermTier.SAFE,
    "memory_read":       PermTier.SAFE,
    "memory_search":     PermTier.SAFE,
    "list_skills":       PermTier.SAFE,
    "get_system_info":   PermTier.SAFE,
    "list_characters":   PermTier.SAFE,
    "get_settings":      PermTier.SAFE,

    # NORMAL — reads with external contact
    "web_search":        PermTier.NORMAL,
    "web_fetch":         PermTier.NORMAL,
    "url_fetch":         PermTier.NORMAL,
    "summarize_url":     PermTier.NORMAL,

    # ELEVATED — writes and spawns
    "write_file":        PermTier.ELEVATED,
    "edit_file":         PermTier.ELEVATED,
    "create_file":       PermTier.ELEVATED,
    "vault_write":       PermTier.ELEVATED,
    "memory_write":      PermTier.ELEVATED,
    "create_skill":      PermTier.ELEVATED,
    "delete_skill":      PermTier.ELEVATED,
    "skill":             PermTier.ELEVATED,
    "screenshot":        PermTier.ELEVATED,
    "reminder":          PermTier.ELEVATED,
    "send_notification": PermTier.ELEVATED,

    # DANGEROUS — system-level
    "shell":             PermTier.DANGEROUS,
    "execute_command":   PermTier.DANGEROUS,
    "delete_file":       PermTier.DANGEROUS,
}


class PermissionGate:
    """
    Interactive permission gate for tool calls.
    Wraps ToolPermissions and adds async user confirmation.

    Three modes:
      "ask"        — confirm every NORMAL+ action individually
      "auto-safe"  — auto-allow SAFE, confirm ELEVATED+
      "allow-all"  — allow everything, log it

    Usage:
        gate = PermissionGate(
            mode="auto-safe",
            ask_fn=ws_confirm_fn,  # async (prompt: str) -> bool
        )
        allowed = await gate.check("write_file", {"path": "test.py"})
    """

    def __init__(
        self,
        mode: str = "auto-safe",
        ask_fn: Optional[Callable[[str], Awaitable[bool]]] = None,
    ):
        self.mode = mode
        self.ask_fn = ask_fn
        # Session-level always-allow decisions
        self._session_always_allow: set[str] = set()

    async def check(self, tool_name: str, tool_input: Optional[dict] = None) -> bool:
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
            tier == PermTier.DANGEROUS  # always ask for DANGEROUS regardless of mode
        )

        if self.mode == "allow-all" and tier != PermTier.DANGEROUS:
            logger.info(f"[perm] auto-allow ({self.mode}): {tool_name}")
            return True

        if needs_ask and self.ask_fn:
            input_preview = ""
            if tool_input:
                key = list(tool_input.keys())[0] if tool_input else ""
                val = str(list(tool_input.values())[0])[:60] if tool_input else ""
                input_preview = f" ({key}={val!r})"

            prompt = (
                f"Allow {tool_name}{input_preview}? "
                f"[tier: {tier.name}] — y/n/always: "
            )
            response = await self.ask_fn(prompt)
            if isinstance(response, str):
                if response.lower() in ("always", "a"):
                    self._session_always_allow.add(tool_name)
                    return True
                return response.lower() in ("y", "yes")
            return bool(response)

        if needs_ask and not self.ask_fn:
            # No ask_fn provided — deny instead of hanging
            logger.info(f"[perm] denied (no ask_fn): {tool_name}")
            return False

        return True

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "session_always_allow": list(self._session_always_allow),
        }
