"""
Autonomous skill curator. Runs weekly as a background asyncio task.
Source: Hermes-Agent's Autonomous Curator — prevents skill rot.

Schedule: run every 7 days. First run: 7 days after first skill is created.
Output: archives bad skills, merges duplicates, writes vault report.

To trigger manually: python -m backend curate
"""
import json
import logging
import math
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.core.paths import SKILLS_DIR, VAULT_DIR

logger = logging.getLogger(__name__)

ARCHIVE_DIR = SKILLS_DIR / ".archive"
CURATOR_STATE = SKILLS_DIR / ".curator_state.json"

MIN_USAGE = 1
STALE_DAYS = 30


class SkillCurator:
    """
    Grades, merges, and archives skills based on usage data from metrics.db.
    """

    def __init__(self, metrics_collector, llm_caller):
        self.metrics = metrics_collector
        self.llm = llm_caller
        self._state_lock = False  # Simple in-memory lock flag

    async def run(self):
        """Full curation cycle. Takes 30-120 seconds. Run in background."""
        logger.info("Skill curator starting")
        start = datetime.now(timezone.utc)

        # Find all skill files: both top-level *.md (legacy) and subdirectory SKILL.md
        skill_files = self._discover_all_skill_files()
        if not skill_files:
            logger.info("Curator: no skills to curate")
            return

        usage = await self._get_usage_stats()

        results = {
            "graded": 0, "archived": 0, "merged": 0,
            "total_skills_before": len(skill_files),
        }

        # Step 1: Grade and archive low-quality skills
        surviving = []
        for skill_path in skill_files:
            name = skill_path.stem
            skill_usage = usage.get(name, 0)
            age_days = self._skill_age_days(skill_path)

            grade = self._grade(skill_usage, age_days)
            results["graded"] += 1

            # Use grade in archival decision: archive if score < 0.2 (very low quality)
            # OR if both low usage AND stale (matches MIN_USAGE/STALE_DAYS fallback)
            if grade < 0.2 or (skill_usage < MIN_USAGE and age_days > STALE_DAYS):
                self._archive(skill_path)
                results["archived"] += 1
                logger.info(f"Archived: {name} (grade={grade:.2f}, used={skill_usage}, age={age_days}d)")
            else:
                surviving.append(skill_path)

        # Step 2: Find and merge semantic duplicates
        if len(surviving) >= 2:
            merged = await self._find_and_merge_duplicates(surviving)
            results["merged"] = merged

        # Step 3: Write vault report
        duration = (datetime.now(timezone.utc) - start).total_seconds()
        report = self._write_report(results, duration)
        report_path = VAULT_DIR / f"curator_report_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report)
        except OSError as e:
            logger.error(f"Failed to write curator report: {e}")

        # Step 4: Update last-run timestamp
        self._save_state(results)

        logger.info(f"Curator done in {duration:.1f}s: {results}")

    def _discover_all_skill_files(self) -> list[Path]:
        """Discover all skill files, including auto-created subdirectory skills.

        Previously used glob(\"*.md\") which missed skills stored as
        ``skill_name/SKILL.md`` by AutoSkillCreator. Now discovers both:
        - ``SKILLS_DIR/*.md`` (legacy flat skills)
        - ``SKILLS_DIR/*/SKILL.md`` (auto-created skills)
        """
        if not SKILLS_DIR.exists():
            return []
        # Top-level .md files
        top_level = list(SKILLS_DIR.glob("*.md"))
        # Subdirectory SKILL.md files (auto-created skills)
        subdir_skills = list(SKILLS_DIR.glob("*/SKILL.md"))
        # Combine and deduplicate by path
        seen = set()
        result = []
        for p in top_level + subdir_skills:
            if p not in seen:
                seen.add(p)
                result.append(p)
        return sorted(result)

    @staticmethod
    def _skill_age_days(skill_path: Path) -> int:
        """Calculate age of a skill file in days.

        Uses ctime (creation time) where available, falling back to mtime.
        Avoids stat-based staleness issues where mtime changes on edit.
        """
        try:
            stat = skill_path.stat()
            # Try birthtime (ctime on Linux), fall back to mtime
            file_time = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
        except (OSError, ValueError):
            return 0
        return (datetime.now(timezone.utc) - file_time).days

    def _grade(self, usage_count: int, age_days: int) -> float:
        """
        Grade a skill 0.0-1.0 based on usage and freshness.
        0.0 = should be archived. 1.0 = excellent, keep.

        Formula: usage score (0-0.7) + freshness score (0-0.3)
        """
        usage_score = min(0.7, 0.35 * math.log1p(usage_count))
        freshness = max(0.0, 1.0 - (age_days / STALE_DAYS)) * 0.3
        return usage_score + freshness

    def _archive(self, path: Path):
        """Move a skill to the archive directory with error handling."""
        try:
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create archive directory: {e}")
            return
        dest = ARCHIVE_DIR / path.name
        try:
            # Use copy + delete instead of shutil.move to avoid cross-device errors
            if dest.exists():
                logger.warning(f"Archive destination already exists: {dest}, overwriting")
            shutil.copy2(str(path), str(dest))
            path.unlink()
            logger.info(f"Archived: {path.name} -> {dest}")
        except (OSError, shutil.Error) as e:
            logger.error(f"Failed to archive {path}: {e}")

    async def _get_usage_stats(self) -> dict[str, int]:
        try:
            report = await self.metrics.report(days=30)
            return {s["skill_used"]: s["uses"] for s in report.get("top_skills", [])}
        except Exception as e:
            logger.debug(f"Could not get usage stats: {e}")
            return {}

    async def _find_and_merge_duplicates(self, skill_paths: list[Path]) -> int:
        from difflib import SequenceMatcher
        merged_count = 0
        processed = set()

        for i, a in enumerate(skill_paths):
            if a in processed:
                continue
            # Read first ~2KB of content for content-based comparison
            try:
                content_a_head = a.read_bytes()[:2048]
            except OSError:
                continue
            for b in skill_paths[i+1:]:
                if b in processed:
                    continue
                # Combine name similarity AND content similarity for better detection
                name_ratio = SequenceMatcher(None, a.stem, b.stem).ratio()
                # Content similarity catches true duplicates even when names differ
                try:
                    content_b_head = b.read_bytes()[:2048]
                    content_ratio = SequenceMatcher(None, content_a_head, content_b_head).ratio()
                except OSError:
                    content_ratio = 0.0
                # Use max of name and content similarity
                similarity = max(name_ratio, content_ratio)
                if similarity > 0.7:
                    logger.info(f"Duplicate candidate: {a.stem} <-> {b.stem} (name_sim={name_ratio:.2f}, content_sim={content_ratio:.2f})")
                    merged = await self._merge_skills(a, b)
                    if merged:
                        processed.add(a)
                        processed.add(b)
                        merged_count += 1
                        break

        return merged_count

    async def _merge_skills(self, path_a: Path, path_b: Path) -> bool:
        try:
            content_a = path_a.read_text(encoding="utf-8")
            content_b = path_b.read_text(encoding="utf-8")

            prompt = f"""These two skills are similar. Merge them into one better skill.
Keep the best parts of each. Use the SKILL.md format.
Respond ONLY with the merged SKILL.md content, no explanation.

SKILL A ({path_a.name}):
{content_a}

SKILL B ({path_b.name}):
{content_b}"""

            merged = await self.llm(prompt, max_tokens=800)
            if not merged or len(merged) < 100:
                return False

            merged_path = path_a
            merged_path.write_text(merged, encoding="utf-8")
            self._archive(path_b)
            logger.info(f"Merged {path_b.name} into {path_a.name}")
            return True

        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"File I/O error during merge: {e}")
            return False
        except Exception as e:
            logger.debug(f"Merge failed: {e}")
            return False

    def _write_report(self, results: dict, duration: float) -> str:
        # Sanitize skill names to prevent markdown injection
        now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        return f"""# Skill Curator Report — {now_str}

## Summary
- Skills before: {results['total_skills_before']}
- Graded: {results['graded']}
- Archived (low quality): {results['archived']}
- Merged (duplicates): {results['merged']}
- Duration: {duration:.1f}s

## Archived Skills
Archived skills are in `{ARCHIVE_DIR}`. Restore by moving back to `{SKILLS_DIR}`.

## Next Run
{(datetime.now(timezone.utc) + timedelta(days=7)).strftime('%Y-%m-%d')}
"""

    def _save_state(self, results: dict):
        """Save curator state with locking to prevent concurrent corruption."""
        if self._state_lock:
            logger.warning("Curator state lock held — skipping state save")
            return
        self._state_lock = True
        try:
            CURATOR_STATE.parent.mkdir(parents=True, exist_ok=True)
            CURATOR_STATE.write_text(json.dumps({
                "last_run": datetime.now(timezone.utc).isoformat(),
                "results": results,
            }, indent=2))
        except OSError as e:
            logger.error(f"Failed to save curator state: {e}")
        finally:
            self._state_lock = False


async def should_run() -> bool:
    """Returns True if 7 days have passed since last curator run."""
    if not CURATOR_STATE.exists():
        return True
    try:
        state = json.loads(CURATOR_STATE.read_text())
        last = datetime.fromisoformat(state["last_run"])
        # Make timezone-aware if naive
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last).days >= 7
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to read curator state: {e}")
        return True
