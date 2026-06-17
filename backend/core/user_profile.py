"""
Persistent user profile — accumulates across sessions.
Updated async after each session ends. Never blocks the main response.
Injected into every system prompt as a compact string (<200 tokens).

Stores: name, timezone, expertise areas, communication style, recurring tasks,
        preferences (freeform key:value), languages spoken.

Source: Hermes-Agent's cross-session user modeling approach.
File lives at: data/user_profile.json
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)
PROFILE_PATH = Path("data/user_profile.json")

# Only these keys are allowed — prevents prompt injection via LLM-generated updates
ALLOWED_KEYS = {
    "name", "timezone", "expertise_areas", "communication_style",
    "recurring_tasks", "preferences", "languages",
}

DEFAULTS = {
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


class UserProfile:

    def __init__(self, path: Path = PROFILE_PATH):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                on_disk = json.loads(self.path.read_text(encoding="utf-8"))
                merged = dict(DEFAULTS)
                merged.update(on_disk)
                return merged
            except Exception as e:
                logger.warning(f"Could not load user profile: {e}")
        profile = dict(DEFAULTS)
        profile["created_at"] = datetime.now().isoformat()
        return profile

    def save(self):
        self._data["last_updated"] = datetime.now().isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def to_context_string(self) -> str:
        """
        Returns a compact string injected into the system prompt.
        Kept under 200 tokens — specific facts only, no padding.
        """
        parts = []
        if self._data.get("name"):
            parts.append(f"User: {self._data['name']}")
        if self._data.get("expertise_areas"):
            parts.append("Expertise: " + ", ".join(self._data["expertise_areas"][:6]))
        style = self._data.get("communication_style", "balanced")
        if style != "balanced":
            parts.append(f"Prefers {style} responses")
        if self._data.get("recurring_tasks"):
            parts.append("Often asks: " + ", ".join(self._data["recurring_tasks"][:4]))
        for k, v in list(self._data.get("preferences", {}).items())[:3]:
            parts.append(f"{k}: {v}")
        langs = self._data.get("languages", [])
        if langs and langs != ["English"]:
            parts.append("Languages: " + ", ".join(langs[:3]))
        if not parts:
            return ""
        return ". ".join(parts) + "."

    async def update_from_session(
        self,
        messages: list[dict],
        llm_caller: Callable[[str], Awaitable[str]],
    ) -> bool:
        """
        After a session, ask the LLM to extract new user info and update the profile.
        Returns True if anything was updated.
        Called as: asyncio.create_task(profile.update_from_session(msgs, llm_fn))
        """
        user_msgs = [
            m["content"][:400]
            for m in messages
            if m.get("role") == "user"
        ][-20:]

        if len(user_msgs) < 3:
            return False

        current = {k: self._data[k] for k in ALLOWED_KEYS if k in self._data}
        convo = "\n".join(f"- {m}" for m in user_msgs)

        prompt = f"""Analyze these user messages. Extract only NEW information about the user.

Current profile:
{json.dumps(current, indent=2)}

User messages:
{convo}

Return a JSON object with only NEW fields. Use these exact keys:
name, timezone, expertise_areas (list), communication_style (one of: concise/detailed/casual/formal/balanced),
recurring_tasks (list), preferences (dict), languages (list).

If nothing new: return {{}}
NO explanation. NO markdown. ONLY valid JSON."""

        try:
            resp = await llm_caller(prompt)
            resp = resp.strip()
            if "```" in resp:
                resp = re.sub(r"```(?:json)?|```", "", resp).strip()

            updates = json.loads(resp)
            if not updates or not isinstance(updates, dict):
                return False

            changed = False
            for key, value in updates.items():
                if key not in ALLOWED_KEYS:
                    continue
                current_val = self._data.get(key)

                if isinstance(value, list) and isinstance(current_val, list):
                    existing = {str(v).lower() for v in current_val}
                    new = [v for v in value if str(v).lower() not in existing]
                    if new:
                        self._data[key].extend(new)
                        changed = True
                elif isinstance(value, dict) and isinstance(current_val, dict):
                    new_entries = {k: v for k, v in value.items() if k not in current_val}
                    if new_entries:
                        self._data[key].update(new_entries)
                        changed = True
                elif value and not current_val:
                    self._data[key] = value
                    changed = True

            if changed:
                self._data["interaction_count"] += 1
                self.save()
                logger.info("User profile updated from session")
            return changed

        except Exception as e:
            logger.debug(f"Profile update skipped (non-fatal): {e}")
            return False
