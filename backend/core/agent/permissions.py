"""Tool permission system — categories of tool access per conversation.

Permission levels:
    "readonly" — only read-only tools allowed
    "confirm" — dangerous tools require user confirmation
    "full" — all tools allowed without confirmation
"""

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


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
    """Per-session tool permission state."""

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
