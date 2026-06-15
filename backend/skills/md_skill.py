"""
SKILL.md loader — parses, discovers, and serves portable skill files.

Each skill is a directory containing a SKILL.md file with YAML frontmatter:
  ---
  name: skill_name
  description: Brief description
  ---
  ## skill_name
  ... markdown body ...
"""

import os
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
BUILTIN_SKILLS = PROJECT_ROOT / "backend" / "skills"
DATA_DIR = Path(os.environ.get("AMALGAM_DATA_DIR", str(PROJECT_ROOT / "data")))
USER_SKILLS = DATA_DIR / "skills"


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
    """Scan user skills directory for SKILL.md files, copying missing built-ins first.

    Returns list of {name, description, path, body} dicts.
    """
    os.makedirs(str(USER_SKILLS), exist_ok=True)
    os.makedirs(str(BUILTIN_SKILLS), exist_ok=True)

    # Copy missing built-in skills to user directory
    for entry in sorted(os.listdir(str(BUILTIN_SKILLS))):
        if entry.startswith(("__", ".")):
            continue
        src = BUILTIN_SKILLS / entry
        dst = USER_SKILLS / entry
        if src.is_dir() and not dst.exists():
            try:
                shutil.copytree(
                    str(src), str(dst),
                    ignore=shutil.ignore_patterns("__pycache__", "*.py"),
                )
                logger.info("Installed built-in skill '%s' to user data", entry)
            except Exception as e:
                logger.warning("Failed to copy skill '%s': %s", entry, e)

    skills = []
    if USER_SKILLS.is_dir():
        for entry in sorted(os.listdir(str(USER_SKILLS))):
            skill_md = USER_SKILLS / entry / "SKILL.md"
            if skill_md.is_file():
                try:
                    content = skill_md.read_text(encoding="utf-8")
                    parsed = parse_skill(content)
                    if parsed["name"]:
                        skills.append({
                            "name": parsed["name"],
                            "description": parsed["description"] or "",
                            "path": str(skill_md),
                            "body": parsed["body"] or "",
                        })
                except Exception as e:
                    logger.warning("Failed to parse skill '%s': %s", entry, e)

    return skills


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
