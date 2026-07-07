#!/usr/bin/env python3
"""Copy valid skill files from ../cloned/skills/ to data/skills/.

Validates that each SKILL.md has proper YAML frontmatter (name + description)
before copying. Preserves the skill directory structure (SKILL.md + any
supporting files like references/, assets/, scripts/).

Skips skills whose names conflict with existing skills already in data/skills/.
"""
import os
import re
import sys
import shutil
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SOURCE_DIR = PROJECT_ROOT / ".." / "cloned" / "skills"
DEST_DIR = PROJECT_ROOT / "data" / "skills"

INJECTION_PATTERNS = [
    "ignore previous instructions",
    "disregard your",
    "you are now",
    "forget everything",
    "jailbreak",
    "new persona",
]

# Files/dirs to skip when copying skill contents
SKIP_PATTERNS = {"__pycache__", "*.pyc", ".DS_Store", "node_modules"}


def parse_frontmatter(content: str) -> dict | None:
    """Extract YAML frontmatter from a SKILL.md file."""
    match = re.match(r"^---\n(.*?)\n---\n?(.*)", content, re.DOTALL)
    if not match:
        return None
    try:
        meta = yaml.safe_load(match.group(1))
        if not isinstance(meta, dict) or "name" not in meta:
            return None
        return meta
    except Exception:
        return None


def is_valid_skill(skill_md_path: Path) -> tuple[bool, str]:
    """Check if a SKILL.md file is a valid skill for this project."""
    try:
        content = skill_md_path.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Cannot read: {e}"

    # Check for injection patterns
    lower = content.lower()
    for pattern in INJECTION_PATTERNS:
        if pattern in lower:
            return False, f"Contains injection pattern: {pattern}"

    # Parse frontmatter
    meta = parse_frontmatter(content)
    if not meta:
        return False, "No valid YAML frontmatter with 'name' field"

    name = meta.get("name", "")
    if not name:
        return False, "Empty 'name' in frontmatter"

    return True, name


def find_all_skill_files() -> list[tuple[Path, str]]:
    """Find all SKILL.md files in the source directory, returning (path, repo)."""
    skills = []
    for repo_dir in sorted(SOURCE_DIR.iterdir()):
        if not repo_dir.is_dir() or repo_dir.name.startswith("."):
            continue
        for skill_md in repo_dir.rglob("SKILL.md"):
            # Only consider files that are directly inside a skill directory
            # (their parent dir is the skill name)
            parent = skill_md.parent
            # Skip if this is nested deep inside a non-skill structure
            skills.append((skill_md, repo_dir.name))
    return skills


def copy_skill(skill_md_path: Path, skill_name: str, repo_name: str) -> tuple[bool, str]:
    """Copy a skill directory to data/skills/<name>/."""
    skill_dir = skill_md_path.parent
    dest_skill_dir = DEST_DIR / skill_name

    if dest_skill_dir.exists():
        return False, f"Already exists: data/skills/{skill_name}/"

    # Copy the entire skill directory
    try:
        shutil.copytree(
            str(skill_dir),
            str(dest_skill_dir),
            ignore=shutil.ignore_patterns(*SKIP_PATTERNS),
        )
        return True, f"Copied from {repo_name}"
    except Exception as e:
        return False, f"Copy failed: {e}"


def main():
    DEST_DIR.mkdir(parents=True, exist_ok=True)

    # Get existing skill names (flat .md files + directories)
    existing_skills = set()
    for f in DEST_DIR.glob("*.md"):
        if f.is_file():
            meta = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
            if meta and "name" in meta:
                existing_skills.add(meta["name"])
    for d in DEST_DIR.iterdir():
        if d.is_dir():
            existing_skills.add(d.name)

    print(f"Existing skills in data/skills/: {len(existing_skills)}")
    print(f"Scanning {SOURCE_DIR} for SKILL.md files...\n")

    skill_files = find_all_skill_files()
    print(f"Found {len(skill_files)} SKILL.md files total\n")

    copied = 0
    skipped_existing = 0
    skipped_invalid = 0
    errors = 0

    for skill_md, repo_name in skill_files:
        valid, result = is_valid_skill(skill_md)
        if not valid:
            print(f"  SKIP (invalid): {skill_md.relative_to(SOURCE_DIR)} - {result}")
            skipped_invalid += 1
            continue

        skill_name = result
        if skill_name in existing_skills:
            print(f"  SKIP (exists):  {skill_name}")
            skipped_existing += 1
            continue

        success, msg = copy_skill(skill_md, skill_name, repo_name)
        if success:
            print(f"  COPIED:         {skill_name} ({msg})")
            existing_skills.add(skill_name)
            copied += 1
        else:
            print(f"  ERROR:          {skill_name} - {msg}")
            errors += 1

    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Copied:        {copied}")
    print(f"  Skipped (exists): {skipped_existing}")
    print(f"  Skipped (invalid): {skipped_invalid}")
    print(f"  Errors:        {errors}")
    print(f"  Total skills in data/skills/: {len(existing_skills)}")

    # Final verification
    print(f"\nVerifying data/skills/ structure...")
    dirs_with_skill_md = 0
    flat_md_files = 0
    for item in DEST_DIR.iterdir():
        if item.is_dir():
            if (item / "SKILL.md").exists():
                dirs_with_skill_md += 1
        elif item.suffix == ".md" and item.is_file():
            flat_md_files += 1
    print(f"  Directory skills (SKILL.md): {dirs_with_skill_md}")
    print(f"  Flat skill files (*.md):     {flat_md_files}")
    print(f"  Total:                       {dirs_with_skill_md + flat_md_files}")


if __name__ == "__main__":
    main()
