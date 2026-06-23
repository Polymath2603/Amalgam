import os
import logging
from pathlib import Path
from typing import List, Dict

import jinja2
from backend.core.paths import PROJECT_ROOT, VAULT_DIR, CHARACTERS_DIR
from backend.core.vault import VaultManager
from backend.core.utils.tokens import estimate_tokens, truncate_to_token_limit
from backend.core.constitution import build_system_prompt
from backend.skills.md_loader import get_loader as _get_skill_loader

# Module-level singleton — lazy-loaded on first use
_user_profile = None

def _get_user_profile():
    """Lazy-initialized user profile singleton."""
    global _user_profile
    if _user_profile is None:
        from backend.core.user_profile import UserProfile
        _user_profile = UserProfile()
    return _user_profile

logger = logging.getLogger(__name__)


def _resolve_model_name(settings) -> str | None:
    """Resolve the model name for token estimation, handling provider-specific prefixes.

    This is a temporary workaround — provider-specific model name normalization
    should eventually live in the LLM router or settings layer.
    """
    if not settings:
        return None
    provider = settings.get("provider.active")
    if not provider:
        return None
    model_raw = settings.get(f"provider.{provider}.model", "")
    if not model_raw:
        return None
    if provider == "groq" and not model_raw.startswith("groq/"):
        return f"groq/{model_raw}"
    return model_raw

_jinja_env = jinja2.Environment(
    loader=jinja2.BaseLoader(),
    undefined=jinja2.Undefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

VRM_EXPRESSIONS = ["happy", "angry", "sad", "relaxed", "surprised", "blink"]

# Voice ID → natural description for prompt injection
_VOICE_DESCRIPTIONS = {
    "en-US-AriaNeural": "a warm, friendly female voice (Aria)",
    "en-US-JaneNeural": "a calm, gentle female voice (Jane)",
    "en-US-GuyNeural": "a friendly male voice (Guy)",
    "en-US-JennyNeural": "a cheerful, warm female voice (Jenny)",
    "en-US-DavisNeural": "a confident male voice (Davis)",
    "en-US-TonyNeural": "a deep, authoritative male voice (Tony)",
    "en-US-NancyNeural": "a playful, expressive female voice (Nancy)",
    "en-US-SaraNeural": "a bright, friendly female voice (Sara)",
    "en-US-JasonNeural": "a calm, reassuring male voice (Jason)",
}


_PROMPT_TEMPLATE = """\

{{ identity }}

Your responses are displayed as chat messages in a web UI.
- The user communicates via text or voice input
- You have a 3D VRM avatar that shows facial expressions and performs full-body animations
- Your voice is synthesized through TTS and can carry emotional tone
- You have a personal knowledge vault for persistent information
- Images sent by the user are visible to you
- You can use connected tools to interact with the local system
- You have access to conversation history within the current session — refer back to earlier topics when relevant

{{ avatar_section }}


{{ character_style }}

- **Consult your Vault for persistent rules (`rules.md`).** The vault contains your core instructions for formatting, tool usage, safety, and edge cases. You must strictly adhere to them.
- Use tools for actions; use text output only for communication.

Your vault is a directory of markdown files you manage yourself via the **obsidian** MCP server tools (`read-note`, `search-vault`, `create-note`, `edit-note`, `delete-note`). This is your permanent memory. Use it deliberately. Refer to `vault_structure.md` in your vault for folder conventions.

- **Keep notes concise**: bullet points, short paragraphs — not full conversation dumps
- **Update, don't duplicate**: `search-vault` before `create-note`
- **Review periodically**: at the start of a session, `search-vault` for notes relevant to the user's context

{{ relationship_section }}\
{{ user_profile_section }}\
{{ vault_rules }}\
{{ tool_section }}\
{{ skill_section }}\
{{ summary_section }}\
{{ relevant_section }}\
{{ reasoning_note }}\
"""


class ContextBuilder:
    def __init__(self, settings=None):
        self.settings = settings

    @property
    def _characters(self) -> Dict[str, Dict]:
        if self.settings:
            return self.settings.get_characters()
        return {}

    def get_character(self, character_id: str) -> Dict:
        return self._characters.get(character_id, {})

    def list_characters(self) -> Dict[str, Dict]:
        return self._characters

    def _get_available_animations(self, character_id: str = None) -> List[str]:
        names = []
        seen = set()
        for base in [CHARACTERS_DIR, PROJECT_ROOT / "backend" / "characters"]:
            anim_dir = base / "default" / "anim"
            if anim_dir.exists():
                for f in sorted(os.listdir(str(anim_dir))):
                    if f.endswith(".vrma") and f not in seen:
                        seen.add(f)
                        name = f.replace(".vrma", "").replace(".bvh", "")
                        names.append(name)
        if character_id and character_id != "default":
            for base in [CHARACTERS_DIR, PROJECT_ROOT / "backend" / "characters"]:
                anim_dir = base / character_id / "anim"
                if anim_dir.exists():
                    for f in sorted(os.listdir(str(anim_dir))):
                        if f.endswith(".vrma") and f not in seen:
                            seen.add(f)
                            name = f.replace(".vrma", "").replace(".bvh", "")
                            names.append(name)
        return names

    def _get_vault_path(self) -> str:
        if self.settings:
            return self.settings.get("vault.path", str(VAULT_DIR))
        return str(VAULT_DIR)

    def _build_vault_section(self) -> str:
        vault_path = self._get_vault_path()
        if not os.path.exists(vault_path):
            return ""

        # Validate vault path against directory traversal
        vault_path = str(Path(vault_path).resolve())
        vault_dir_resolved = str(Path(VAULT_DIR).resolve())
        if not vault_path.startswith(vault_dir_resolved):
            logger.warning(f"Vault path traversal blocked: {vault_path}")
            return ""

        rules_path = os.path.join(vault_path, "rules.md")
        if os.path.exists(rules_path) and os.path.isfile(rules_path):
            try:
                with open(rules_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:

                    max_tokens = 200
                    model = None
                    if self.settings:
                        max_tokens = int(self.settings.get("vault.inject_tokens", max_tokens))
                        model = _resolve_model_name(self.settings)
                    if estimate_tokens(content, model=model) > max_tokens:
                        content = truncate_to_token_limit(content, max_tokens, model=model)
                    return f"\n\n{content}"
            except Exception as e:
                logger.warning(f"Failed to read rules.md: {e}")

        return ""

    async def build(self, tools: List[Dict], history: List[Dict], user_msg: str,
              character_id: str = None, additional_prompt: str = "",
              summary: str = "", relevant: List[Dict] = None,
              tts_emotions: List[str] = None, expression_names: List[str] = None,
              relationship_context: str = "", native_tools_available: bool = False) -> list:
        if not character_id and self.settings:
            character_id = self.settings.get("character.active", "default")
        character = self._characters.get(character_id, {})

        char_ctx = await self._build_character_prompt(
            character, additional_prompt, character_id, tools
        )

        tool_section = self._build_tool_section(tools, native_tools_available=native_tools_available)
        skill_section = self._build_skills_for_query(user_msg)
        summary_section = self._build_summary_section(summary)
        relevant_section = self._build_relevant_section(relevant)
        relationship_section = self._build_relationship_section(relationship_context)

        user_profile_section = self._build_user_profile_section()

        template = _jinja_env.from_string(_PROMPT_TEMPLATE)
        sys_prompt = template.render(
            **char_ctx,
            tool_section=tool_section,
            skill_section=skill_section,
            summary_section=summary_section,
            relevant_section=relevant_section,
            relationship_section=relationship_section,
            user_profile_section=user_profile_section,
        )

        max_sys_tokens = 1500
        model = None
        if self.settings:
            max_sys_tokens = int(self.settings.get("system_prompt.max_tokens", max_sys_tokens))
            model = _resolve_model_name(self.settings)

        if estimate_tokens(sys_prompt, model=model) > max_sys_tokens:
            sys_prompt = truncate_to_token_limit(sys_prompt, max_sys_tokens, model=model)
            logger.debug(f"System prompt truncated to {max_sys_tokens} tokens")

        messages = [{"role": "system", "content": sys_prompt}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_msg})

        return messages

    def _build_tool_section(self, tools: List[Dict], native_tools_available: bool = False) -> str:
        if not tools:
            return ""
        lines = ["\n\n### Available Tools"]
        lines.append("You have access to the following tools. Use them when appropriate — do not preemptively refuse to call them. If a tool call is blocked or needs permission, the system will prompt the user automatically.")
        lines.append("You can call multiple tools in sequence — after a tool result arrives, you may call another tool or respond to the user.")

        def _tool_name(t):
            return t.get('function', {}).get('name', t.get('name', ''))
        def _tool_desc(t):
            return t.get('function', {}).get('description', t.get('description', ''))
        def _tool_params(t):
            f = t.get('function', t)
            return f.get('parameters', {})

        skill_names = {'skill', 'create_skill', 'delete_skill', 'list_skills'}
        skill_tools = [t for t in tools if _tool_name(t) in skill_names]
        other_tools = [t for t in tools if _tool_name(t) not in skill_names]
        has_skills = bool(skill_tools)

        if has_skills:
            lines.append("\n### Task Tool")
            lines.append("You can spawn a sub-agent for focused, self-contained tasks using the `task` tool. The sub-agent has the same capabilities (MCP tools, LLM) but runs in an isolated context. Use this for tasks independent of the current conversation, such as code reviews, document generation, or research. Returns the sub-agent's complete output.")
            lines.append("\n### Skills")
            lines.append("Skills are reusable knowledge files (SKILL.md) you can load on-demand.")
            lines.append("Use `list_skills` to see available skills, then `skill(\"name\")` to load one into context when a task matches its description.")
            lines.append("Use `create_skill` to save useful patterns, conventions, or knowledge as new skills for future reuse.")
            lines.append("Consider loading a relevant skill whenever a task involves a known framework, tool, or domain — the skill content will give you precise guidance.")

        for t in other_tools:
            lines.append(f"\n### {_tool_name(t)}")
            lines.append(_tool_desc(t))
            params = _tool_params(t)
            if params.get('properties'):
                for k, v in params['properties'].items():
                    lines.append(f"  - {k} ({v.get('type', 'string')})")

        if not native_tools_available:
            lines.append(
                '\n\nTo invoke a tool, respond with a tool block:\n'
                '```tool\n{"name": "<tool_name>", "arguments": {"<param>": "<value>"}}\n```'
            )
        return "\n".join(lines)

    def _build_summary_section(self, summary: str) -> str:
        if not summary:
            return ""
        return f"\n\n{summary}"

    def _build_relevant_section(self, relevant: List[Dict]) -> str:
        if not relevant:
            return ""
        lines = ["\n\n### Relevant Context"]
        for r in relevant:
            lines.append(f"- {r['role']}: {r['content']}")
        return "\n".join(lines)

    def _build_user_profile_section(self) -> str:
        """Build the user profile section for the system prompt."""
        profile_str = _get_user_profile().to_context_string()
        if not profile_str:
            return ""
        return f"\n\n### About the User\n{profile_str}"

    def _build_skills_for_query(self, query: str) -> str:
        """Inject matching skills into the system prompt per plan spec.
        Uses MDSkillLoader.for_query() to find skills matching the user message.
        """
        loader = _get_skill_loader()
        active = loader.for_query(query, max_skills=2)
        if not active:
            return ""
        return "\n\n" + "\n\n".join(s.to_prompt_injection() for s in active)

    def _build_relationship_section(self, relationship_context: str) -> str:
        if not relationship_context:
            return ""
        return f"\n\n### About the User (from previous interactions)\n{relationship_context}"

    async def _build_character_prompt(self, character: Dict, additional_prompt: str = "",
                                character_id: str = None, tools: list = None) -> dict:
        name = character.get("name", "Assistant") if character else "Assistant"
        system_prompt = character.get("system_prompt", "") if character else ""
        vocabulary = character.get("vocabulary", []) if character else []
        dialogue_examples = character.get("dialogue_examples", []) if character else []
        quirks = character.get("quirks", []) if character else []
        memory_bias = character.get("memory_bias", []) if character else []
        forbidden = character.get("forbidden", []) if character else []
        char_desc = character.get("description", "") if character else ""
        mood = character.get("mood_baseline") if character else None
        volatility = character.get("mood_volatility") if character else None
        voice = character.get("voice", "") if character else ""
        greeting = character.get("greeting", "") if character else ""

        # --- Identity: constitution + description + system_prompt ---
        identity_content = system_prompt or f"You are {name}, a helpful AI assistant."
        if char_desc:
            identity_content = f"### About You\n{char_desc}\n\n{identity_content}"
        identity = await build_system_prompt(
            character_soul=identity_content,
            character_name=name,
        )

        # --- Character style: non-redundant metadata only ---
        style_parts = []

        if voice:
            voice_desc = _VOICE_DESCRIPTIONS.get(
                voice, f"a distinctive voice ({voice})"
            )
            style_parts.append(f"Your voice: {voice_desc}.")

        if vocabulary:
            quoted = ' '.join(f'"{p}"' for p in vocabulary)
            style_parts.append(f"Signature phrases: {quoted}")

        if quirks:
            style_parts.append(f"Quirks: {'; '.join(quirks)}")

        if memory_bias:
            style_parts.append(f"Always remember: {'; '.join(memory_bias)}")

        if forbidden:
            formatted = "\n".join(f"- {f}" for f in forbidden)
            style_parts.append(f"🚫 ABSOLUTE FORBIDDEN — never engage with:\n{formatted}")

        if mood is not None:
            mood_info = f"Your default mood level is {mood}"
            if volatility is not None:
                mood_info += f" and your mood changes at a rate of {volatility}"
            style_parts.append(mood_info + ".")

        character_style = "\n\n".join(style_parts) if style_parts else "Be warm, natural, and engaging."

        if dialogue_examples:
            character_style += (
                "\n\n### Dialogue Examples\n"
                "These are stylistic references — use them as tone inspiration, not verbatim templates:"
            )
            for ex in dialogue_examples:
                character_style += f'\n- "{ex}"'

        if additional_prompt and additional_prompt.strip():
            character_style += f"\n\n{additional_prompt}"

        # --- Character behavior rules (from settings UI) ---
        if self.settings:
            behavior_rules = self.settings.get("character.rules", "")
            if behavior_rules and behavior_rules.strip():
                character_style += f"\n\n### Behavior Rules\n{behavior_rules.strip()}"

        # --- Avatar section ---
        anims = self._get_available_animations(character_id)
        if anims:
            anim_lines = "\n".join(f"  - \"{a}\"" for a in anims)
            action_notes = f"Available actions to pass to avatar_perform_action:\n{anim_lines}"
        else:
            action_notes = "No predefined animations — describe the action naturally (e.g. \"nods thoughtfully\", \"waves happily\"). The system will attempt to match it to an animation."

        has_avatar = tools and any(
            t.get("function", {}).get("name", "").startswith("avatar_")
            for t in tools
        )
        if has_avatar:
            avatar_section = (
                "# Avatar Control (use MCP tools instead of text tags)\n"
                "You control your avatar's expressions, voice emotion, and body animations exclusively through the **avatar** MCP server tools. Do NOT use /[[emotion]] /((expression)) /**action**/ tags — use the tools below instead.\n"
                "\n"
                "# avatar_set_voice_emotion\n"
                "Sets the emotional tone of your spoken voice. Call this when your character's emotional state shifts.\n"
                "Available emotions: happy, sad, angry, surprised, thinking, relaxed, confused, shy, jealous, bored, suspicious, victory, sleep, love, excited\n"
                "- Use one call per response to set your vocal tone\n"
                "- Voice emotion is independent of facial expression\n"
                "\n"
                "# avatar_set_expression\n"
                "Sets your avatar's facial expression (VRM blend shape) independently of voice emotion.\n"
                "Available expressions: happy, angry, sad, relaxed, surprised, blink\n"
                "- Use when your character's face should show an emotion distinct from their voice\n"
                "\n"
                "# avatar_perform_action\n"
                "Triggers a full-body gesture or animation. Describe the action naturally.\n"
                f"{action_notes}\n"
                "- Use when your character would physically gesture (bow, wave, nod, react)\n"
                "- Keep descriptions brief and natural\n"
                "- Not every response needs an action — reserve for meaningful moments"
            )
        else:
            avatar_section = ""

        # --- Vault rules ---
        vault_rules = self._build_vault_section()

        # --- Reasoning note ---
        if self.settings and not self.settings.get("ui.thinking_enabled", True):
            reasoning_note = ""
        else:
            reasoning_note = "\n\nFor reasoning models, use <think>your reasoning</think> before your response."

        return {
            "identity": identity,
            "avatar_section": avatar_section,
            "character_style": character_style,
            "vault_rules": vault_rules,
            "reasoning_note": reasoning_note,
            "greeting": greeting,
        }

    def build_from_messages(self, messages: list, new_user_msg: str) -> list:
        """Append a new user message to a message list.

        Returns a new list without mutating the input (immutable style).
        """
        return messages + [{"role": "user", "content": new_user_msg}]
