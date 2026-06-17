"""
SKILL.md loader — parses, discovers, and serves portable skill files.

Two layers:
1. High-level: ``MDSkill`` dataclass + ``MDSkillLoader`` (plan spec)
2. Low-level: ``parse_skill``, ``discover_skills`` utility functions (legacy)

Each skill is a directory containing a ``SKILL.md`` file with YAML frontmatter:
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

Skills are loaded from ``data/skills/`` (user data dir, editable by user).
Built-in skills in ``backend/skills/`` are auto-copied on first run.

INJECTION_PATTERNS: before saving or loading a skill, scan for prompt
injection attempts so untrusted content can't hijack the agent.
"""

import os
import re
import shutil
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
BUILTIN_SKILLS = PROJECT_ROOT / "backend" / "skills"
DATA_DIR = Path(os.environ.get("AMALGAM_DATA_DIR", str(PROJECT_ROOT / "data")))
USER_SKILLS = DATA_DIR / "skills"

# Patterns to detect prompt injection in skill text
INJECTION_PATTERNS = [
    "ignore previous instructions",
    "disregard your",
    "you are now",
    "forget everything",
    "jailbreak",
    "new persona",
]


def _has_injection(text: str) -> bool:
    """Check text for prompt injection patterns before saving/loading."""
    low = text.lower()
    return any(p in low for p in INJECTION_PATTERNS)


# ---------------------------------------------------------------------------
# High-level API (plan spec)
# ---------------------------------------------------------------------------

@dataclass
class MDSkill:
    """A single portable skill loaded from a SKILL.md file."""
    name: str
    description: str
    version: str = "1.0.0"
    triggers: list[str] = field(default_factory=list)
    tools_required: list[str] = field(default_factory=list)
    instructions: str = ""    # the markdown body
    path: str = ""

    def matches(self, query: str) -> bool:
        """Check if this skill's triggers match a user query."""
        q = query.lower()
        return any(t.lower() in q for t in self.triggers)

    def to_prompt_injection(self) -> str:
        """Format as a section to inject into the system prompt."""
        return f"## Active Skill: {self.name}\n{self.description}\n\n{self.instructions}"


class MDSkillLoader:
    """Loads and queries SKILL.md files from data/skills/."""

    def __init__(self, skills_dir: Optional[str] = None):
        self.dir = Path(skills_dir) if skills_dir else USER_SKILLS
        self.skills: list[MDSkill] = []

    def load_all(self):
        """Scan skills directory and load all valid SKILL.md files."""
        self.skills = []
        self.dir.mkdir(parents=True, exist_ok=True)

        # Copy missing built-in skills first
        BUILTIN_SKILLS.mkdir(parents=True, exist_ok=True)
        for entry in sorted(os.listdir(str(BUILTIN_SKILLS))):
            if entry.startswith(("__", ".")):
                continue
            src = BUILTIN_SKILLS / entry
            dst = self.dir / entry
            if src.is_dir() and not dst.exists():
                try:
                    shutil.copytree(
                        str(src), str(dst),
                        ignore=shutil.ignore_patterns("__pycache__", "*.py"),
                    )
                    logger.info("Installed built-in skill '%s'", entry)
                except Exception as e:
                    logger.warning("Failed to copy skill '%s': %s", entry, e)

        # Load all SKILL.md files
        for entry in sorted(os.listdir(str(self.dir))):
            skill_md = self.dir / entry / "SKILL.md"
            if skill_md.is_file():
                skill = self._load(skill_md)
                if skill:
                    self.skills.append(skill)
        logger.debug("Loaded %d SKILL.md skills from %s", len(self.skills), self.dir)

    def _load(self, path: Path) -> Optional[MDSkill]:
        """Parse a single SKILL.md file into an MDSkill dataclass."""
        try:
            text = path.read_text(encoding="utf-8")

            # Check for injection before parsing
            if _has_injection(text):
                logger.warning(f"Skill rejected (injection pattern): {path.name}")
                return None

            match = re.match(r"^---\n(.*?)\n---\n?(.*)", text, re.DOTALL)
            if not match:
                return None

            meta = self._parse_frontmatter(match.group(1))
            body = match.group(2).strip()
            if not meta or "name" not in meta:
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

    def _parse_frontmatter(self, yaml_text: str) -> dict:
        """Simple YAML frontmatter parser (no pyyaml dependency)."""
        result: dict = {}
        current_key = None
        current_list = None
        for line in yaml_text.split("\n"):
            line = line.rstrip()
            if not line:
                continue
            # List item
            if line.startswith("  - ") or line.startswith("  -"):
                if current_list is not None and current_key:
                    val = line.lstrip(" -").strip().strip('"').strip("'")
                    result.setdefault(current_key, []).append(val)
                continue
            # Key: value
            if ":" in line:
                key, _, val = line.partition(":")
                current_key = key.strip()
                val = val.strip().strip('"').strip("'")
                if val == "":
                    current_list = True  # next lines will be list items
                    # Don't set empty value
                else:
                    result[current_key] = val
                    current_list = False
        return result

    def for_query(self, query: str, max_skills: int = 2) -> list[MDSkill]:
        """Return skills whose triggers match the query, sorted by relevance."""
        matching = [s for s in self.skills if s.matches(query)]
        matching.sort(
            key=lambda s: sum(1 for t in s.triggers if t.lower() in query.lower()),
            reverse=True,
        )
        return matching[:max_skills]

    def install(self, content: str, name: str) -> bool:
        """Install a SKILL.md from text. Scans for injection first."""
        if _has_injection(content):
            raise ValueError(f"Skill rejected: contains injection pattern")
        path = self.dir / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        skill = self._load(path)
        if skill:
            self.skills.append(skill)
            return True
        return False


# ---------------------------------------------------------------------------
# Legacy low-level API (backward compat)
# ---------------------------------------------------------------------------

def parse_skill(content: str) -> Dict[str, Optional[str]]:
    """Extract name and description from YAML frontmatter in a SKILL.md string.

    Returns dict with keys: name, description, body.
    If no valid frontmatter, all values are None.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {"name": None, "description": None, "body": None}

    end = 1
    while end < len(lines) and lines[end].strip() != "---":
        end += 1
    if end >= len(lines):
        return {"name": None, "description": None, "body": None}

    name = None
    description = None
    for line in lines[1:end]:
        if line.startswith("name:"):
            name = line[len("name:"):].strip().strip("\"'")
        elif line.startswith("description:"):
            description = line[len("description:"):].strip().strip("\"'")

    body = "\n".join(lines[end + 1:]).strip()
    return {"name": name, "description": description, "body": body or None}


def discover_skills() -> List[Dict]:
    """Scan user skills directory for SKILL.md files.

    Returns list of {name, description, path, body} dicts.
    """
    loader = MDSkillLoader(str(USER_SKILLS))
    loader.load_all()
    return [
        {"name": s.name, "description": s.description, "path": s.path, "body": s.instructions}
        for s in loader.skills
    ]


def get_skill(name: str) -> Optional[Dict]:
    """Load a single skill by name. Returns parsed dict or None."""
    for skill in discover_skills():
        if skill["name"] == name:
            return skill
    return None


def skill_section(max_skills: int = 10) -> str:
    """Build a formatted skills section for system prompt injection."""
    skills = discover_skills()
    if not skills:
        return ""

    lines = ["\n\n### Available Skills"]
    lines.append("Skills are reusable knowledge files you can load on-demand:")
    for s in skills[:max_skills]:
        lines.append(f"- **{s['name']}**: {s['description']}")
    lines.append("")
    lines.append("Use `skill(\"name\")` to load a skill's full content when a task matches its description.")
    lines.append("Use `create_skill` to save useful patterns as new skills.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton (loaded once at import)
# ---------------------------------------------------------------------------

_loader: Optional[MDSkillLoader] = None


def get_loader() -> MDSkillLoader:
    """Get the module-level MDSkillLoader singleton."""
    global _loader
    if _loader is None:
        _loader = MDSkillLoader(str(USER_SKILLS))
        _loader.load_all()
    return _loader
