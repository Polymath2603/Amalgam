"""
Persistent user profile — what the agent learns about the user across sessions.

The profile is stored at data/user_profile.json.
It grows over time: after each session, the agent extracts new information.
It is injected into the system prompt at the start of every turn.

Design decisions:
- Plain JSON file (not SQLite) — easy to inspect and edit manually
- Merge-on-update (never overwrites existing data with None/empty)
- LLM extracts updates after each session (async, non-blocking)
- to_context_string() keeps output under 200 tokens (measured conservatively)
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Awaitable, Optional

logger = logging.getLogger(__name__)


class UserProfile:

    # Keys that are allowed in the profile.
    # The LLM is only allowed to set these keys — prevents prompt injection
    # where a malicious message tries to set arbitrary profile fields.
    ALLOWED_KEYS = {
        "name",               # str — user's name
        "timezone",           # str — e.g., "UTC+1", "America/New_York"
        "expertise_areas",    # list[str] — topics user knows well
        "communication_style", # str — "concise" | "detailed" | "casual" | "formal"
        "recurring_tasks",    # list[str] — things user asks about often
        "preferences",        # dict[str, str] — freeform key:value preferences
        "languages",          # list[str] — languages the user speaks
    }

    DEFAULT_PROFILE = {
        "name": None,
        "timezone": None,
        "expertise_areas": [],
        "communication_style": "balanced",
        "recurring_tasks": [],
        "preferences": {},
        "languages": ["English"],
        "interaction_count": 0,
        "created_at": None,
        "last_updated": None,
    }

    def __init__(self, data_dir: str = "data"):
        self.path = Path(data_dir) / "user_profile.json"
        self._profile = self._load()

    def _load(self) -> dict:
        """Load profile from disk. Returns default if file doesn't exist or is corrupt."""
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                # Merge with defaults so new keys are always present
                merged = dict(self.DEFAULT_PROFILE)
                merged.update(data)
                return merged
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load user profile: {e} — using defaults")
        profile = dict(self.DEFAULT_PROFILE)
        profile["created_at"] = datetime.now().isoformat()
        return profile

    def save(self):
        """Write profile to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._profile["last_updated"] = datetime.now().isoformat()
        try:
            self.path.write_text(
                json.dumps(self._profile, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except OSError as e:
            logger.error(f"Failed to save user profile: {e}")

    def get(self, key: str, default=None) -> Any:
        return self._profile.get(key, default)

    def to_context_string(self) -> str:
        """
        Generate a compact string for injecting into the system prompt.
        Intentionally kept short (<= 200 tokens) to not waste context budget.

        Returns empty string if profile has no useful information yet.

        Example output:
        'User: Alex. Expertise: Python, ML, distributed systems.
         Prefers concise responses. Often asks about: debugging, architecture.'
        """
        parts = []

        if self._profile.get("name"):
            parts.append(f"User: {self._profile['name']}")

        expertise = self._profile.get("expertise_areas", [])
        if expertise:
            # Cap at 6 items to keep it short
            areas_str = ", ".join(expertise[:6])
            parts.append(f"Expertise: {areas_str}")

        style = self._profile.get("communication_style", "balanced")
        if style and style != "balanced":
            parts.append(f"Prefers {style} responses")

        tasks = self._profile.get("recurring_tasks", [])
        if tasks:
            tasks_str = ", ".join(tasks[:4])
            parts.append(f"Often asks about: {tasks_str}")

        prefs = self._profile.get("preferences", {})
        for k, v in list(prefs.items())[:4]:
            parts.append(f"{k}: {v}")

        langs = self._profile.get("languages", [])
        if langs and langs != ["English"]:
            parts.append(f"Languages: {', '.join(langs[:3])}")

        if not parts:
            return ""

        return ". ".join(parts) + "."

    async def update_from_session(
        self,
        messages: list[dict],
        llm_caller: Callable[[str], Awaitable[str]],
    ) -> bool:
        """
        Extract new user information from a completed session and update the profile.

        Parameters
        ----------
        messages : list[dict]
            The session's messages: [{"role": "user"|"assistant", "content": "..."}, ...]
        llm_caller : async callable
            An async function that takes a prompt string and returns a response string.
            Example: async def call(prompt): return await llm.complete(prompt)

        Returns
        -------
        bool
            True if the profile was updated, False if nothing new was found.
        """
        # Need at least 3 messages to extract meaningful information
        if len(messages) < 3:
            return False

        # Build conversation text. Only look at user messages (not assistant).
        # Cap at last 20 user messages to keep the prompt short.
        user_messages = [
            m["content"][:400]  # truncate long messages
            for m in messages
            if m.get("role") == "user"
        ][-20:]

        if not user_messages:
            return False

        conversation_text = "\n".join(f"- {msg}" for msg in user_messages)

        # Current profile (only the fields the LLM should know about)
        current = {k: self._profile[k] for k in self.ALLOWED_KEYS if k in self._profile}

        prompt = f"""Analyze these user messages and extract factual information about the user.

Current known profile:
{json.dumps(current, indent=2)}

User messages from this session:
{conversation_text}

Extract ONLY new information not already in the profile.
Only include facts clearly stated or strongly implied. Do not guess or infer weakly.

Respond with a JSON object containing only the fields that have NEW information.
Use these exact field names: name, timezone, expertise_areas, communication_style,
recurring_tasks, preferences, languages.

For list fields (expertise_areas, recurring_tasks, languages): return a list of strings.
For preferences: return a dict of string key-value pairs.
For communication_style: use one of: concise, detailed, casual, formal, balanced.

If nothing new was learned, respond with exactly: {{}}

Rules:
- Do NOT include fields already in the profile unless the value changed
- Do NOT make up information
- Do NOT include the assistant's name or any assistant information
- Respond ONLY with a valid JSON object, no explanation, no markdown

Example valid response (only when those things were actually said):
{{"name": "Alex", "expertise_areas": ["Python", "machine learning"]}}"""

        try:
            response = await llm_caller(prompt)
            response = response.strip()

            # Strip markdown code fences if the LLM added them despite instructions
            if response.startswith("```"):
                lines = response.split("\n")
                # Remove first line (```json or ```) and last line (```)
                response = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            updates = json.loads(response)

            if not updates or not isinstance(updates, dict):
                return False

            # Apply updates — only for allowed keys, using merge logic
            changed = False
            for key, value in updates.items():
                if key not in self.ALLOWED_KEYS:
                    logger.debug(f"Skipping disallowed profile key: {key}")
                    continue

                current_val = self._profile.get(key)

                if isinstance(value, list) and isinstance(current_val, list):
                    # Merge lists, removing duplicates (case-insensitive for strings)
                    existing_lower = {str(v).lower() for v in current_val}
                    new_items = [v for v in value if str(v).lower() not in existing_lower]
                    if new_items:
                        self._profile[key].extend(new_items)
                        changed = True

                elif isinstance(value, dict) and isinstance(current_val, dict):
                    # Merge dicts — new keys added, existing keys not overwritten
                    new_keys = {k: v for k, v in value.items() if k not in current_val}
                    if new_keys:
                        self._profile[key].update(new_keys)
                        changed = True

                elif value and not current_val:
                    # Only set if profile field is currently empty
                    self._profile[key] = value
                    changed = True

            if changed:
                self._profile["interaction_count"] = self._profile.get("interaction_count", 0) + 1
                self.save()
                logger.info("User profile updated from session")

            return changed

        except json.JSONDecodeError:
            logger.debug("Profile update: LLM returned non-JSON (expected if nothing new)")
            return False
        except Exception as e:
            logger.warning(f"Profile update failed (non-fatal): {e}")
            return False
