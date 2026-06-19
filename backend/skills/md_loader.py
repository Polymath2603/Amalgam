"""
Loads SKILL.md files from data/skills/ and exposes them for context injection.

SKILL.md format:
---
name: deep-web-research
description: Multi-source research with contradiction detection
version: 1.0.0
triggers:
  - "research"
  - "find information about"
tools_required: [web_search, url_fetch]
---
## When to use...
## Process...
## Notes...

These skills are NOT Python — the LLM reads the instructions and follows them.
Python skills in backend/skills/*/skill.py still work for code-requiring skills.
Both types coexist.
"""
import re
import yaml
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from backend.core.paths import DATA_DIR
SKILLS_DIR = DATA_DIR / "skills"

INJECTION_PATTERNS = [
    "ignore previous instructions",
    "disregard your",
    "you are now",
    "forget everything",
    "jailbreak",
    "new persona",
]


@dataclass
class MDSkill:
    name: str
    description: str
    version: str = "1.0.0"
    triggers: list[str] = field(default_factory=list)
    tools_required: list[str] = field(default_factory=list)
    instructions: str = ""    # the markdown body
    path: str = ""

    def matches(self, query: str) -> bool:
        q = query.lower()
        return any(t.lower() in q for t in self.triggers)

    def to_prompt_injection(self) -> str:
        return f"## Active Skill: {self.name}\n{self.description}\n\n{self.instructions}"


class MDSkillLoader:
    def __init__(self, skills_dir: str = "data/skills"):
        self.dir = Path(skills_dir)
        self.skills: list[MDSkill] = []

    def load_all(self):
        self.skills = []
        self.dir.mkdir(parents=True, exist_ok=True)
        for f in self.dir.glob("*.md"):
            skill = self._load(f)
            if skill:
                self.skills.append(skill)
        logger.info(f"Loaded {len(self.skills)} SKILL.md skills from {self.dir}")

    def _load(self, path: Path) -> MDSkill | None:
        try:
            text = path.read_text(encoding="utf-8")
            # Check for injection before parsing
            if any(p in text.lower() for p in INJECTION_PATTERNS):
                logger.warning(f"Skill rejected (injection pattern): {path.name}")
                return None
            match = re.match(r"^---\n(.*?)\n---\n?(.*)", text, re.DOTALL)
            if not match:
                return None
            meta = yaml.safe_load(match.group(1))
            body = match.group(2).strip()
            if not isinstance(meta, dict) or "name" not in meta:
                return None
            return MDSkill(
                name=meta["name"],
                description=meta.get("description", ""),
                version=str(meta.get("version", "1.0.0")),
                triggers=meta.get("triggers", []),
                tools_required=meta.get("tools_required", []),
                instructions=body,
                path=str(path),
            )
        except Exception as e:
            logger.debug(f"Failed to load skill {path.name}: {e}")
            return None

    def for_query(self, query: str, max_skills: int = 2) -> list[MDSkill]:
        matching = [s for s in self.skills if s.matches(query)]
        matching.sort(
            key=lambda s: sum(1 for t in s.triggers if t.lower() in query.lower()),
            reverse=True,
        )
        return matching[:max_skills]

    def install(self, content: str, name: str) -> bool:
        """Install a SKILL.md from text. Scans for injection first."""
        if any(p in content.lower() for p in INJECTION_PATTERNS):
            raise ValueError(f"Skill rejected: contains injection pattern")
        path = self.dir / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        skill = self._load(path)
        if skill:
            self.skills.append(skill)
            return True
        return False


# Module-level singleton
_skill_loader: MDSkillLoader | None = None


def get_loader() -> MDSkillLoader:
    global _skill_loader
    if _skill_loader is None:
        _skill_loader = MDSkillLoader(str(SKILLS_DIR))
        _skill_loader.load_all()
    return _skill_loader
