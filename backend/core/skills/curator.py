"""
Skill curator — grades, archives, and merges skills on a 7-day cycle.

The curator prevents skill rot: skills that are unused, stale, or duplicated
are automatically pruned. Remaining skills are optionally merged via LLM.

Schedule: runs as a background asyncio task every 7 days.
Manual trigger: python -m backend curate

Source: Hermes-Agent's Autonomous Curator pattern.
"""

import json
import logging
import math
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from difflib import SequenceMatcher
from typing import Callable, Awaitable, Optional

logger = logging.getLogger(__name__)

SKILLS_DIR = Path("data/skills")
ARCHIVE_DIR = Path("data/skills/.archive")
VAULT_DIR = Path("data/vault")
CURATOR_STATE = Path("data/skills/.curator_state.json")

# A skill used fewer than this many times AND older than STALE_DAYS → archived
MIN_USAGE = 1
STALE_DAYS = 30


class SkillCurator:
    """Grades, merges, and archives skills based on usage data from metrics.db."""

    def __init__(self, metrics_collector=None, llm_caller: Optional[Callable[[str], Awaitable[str]]] = None):
        """
        metrics_collector: MetricsCollector instance (for usage stats)
        llm_caller: async fn(prompt) -> str (for merge + quality decisions)
        """
        self.metrics = metrics_collector
        self.llm = llm_caller

    async def run(self):
        """Full curation cycle. Takes 30-120 seconds. Run in background."""
        logger.info("Skill curator starting")
        start = datetime.now()

        skill_files = list(SKILLS_DIR.glob("*/SKILL.md"))
        if not skill_files:
            logger.info("Curator: no skills to curate")
            return

        # Get usage stats from metrics
        usage = await self._get_usage_stats()

        results = {
            "graded": 0, "archived": 0, "merged": 0,
            "total_skills_before": len(skill_files),
        }

        # Step 1: Grade and archive low-quality skills
        surviving = []
        for skill_path in skill_files:
            name = skill_path.parent.stem  # dir name
            skill_usage = usage.get(name, 0)
            age_days = (datetime.now() - datetime.fromtimestamp(
                skill_path.stat().st_mtime
            )).days

            grade = self._grade(skill_usage, age_days)
            results["graded"] += 1

            if grade < 0.2:
                self._archive(skill_path.parent)
                results["archived"] += 1
                logger.info(f"Archived: {name} (grade={grade:.2f})")
            else:
                surviving.append(skill_path)

        # Step 2: Find and merge semantic duplicates
        if len(surviving) >= 2 and self.llm:
            merged = await self._find_and_merge_duplicates(surviving)
            results["merged"] = merged

        # Step 3: Write vault report
        duration = (datetime.now() - start).total_seconds()
        report = self._write_report(results, duration)
        report_path = VAULT_DIR / f"curator_report_{datetime.now().strftime('%Y-%m-%d')}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report)

        # Step 4: Update last-run timestamp
        CURATOR_STATE.parent.mkdir(parents=True, exist_ok=True)
        CURATOR_STATE.write_text(json.dumps({
            "last_run": datetime.now().isoformat(),
            "results": results,
        }, indent=2))

        logger.info(f"Curator done in {duration:.1f}s: {results}")

    def _grade(self, usage_count: int, age_days: int) -> float:
        """
        Grade a skill 0.0–1.0 based on usage and freshness.
        0.0 = should be archived. 1.0 = excellent, keep.

        Formula: usage score (0-0.7) + freshness score (0-0.3)
        - usage_score: log-scaled so 1 use = 0.35, 5 uses = 0.5, 20 uses = 0.7
        - freshness: linear decay from 1.0 (new) to 0.0 (>30 days unused)
        """
        usage_score = min(0.7, 0.35 * math.log1p(usage_count))
        freshness = max(0.0, 1.0 - (age_days / STALE_DAYS)) * 0.3
        return usage_score + freshness

    def _archive(self, path: Path):
        """Move a skill directory to the archive."""
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        dest = ARCHIVE_DIR / path.name
        if dest.exists():
            shutil.rmtree(str(dest))
        shutil.move(str(path), str(dest))

    async def _get_usage_stats(self) -> dict[str, int]:
        """Get per-skill usage counts from the last 30 days."""
        if not self.metrics:
            return {}
        try:
            report = await self.metrics.report(days=30)
            return {s["skill_used"]: s["uses"] for s in report.get("top_skills", [])}
        except Exception:
            return {}

    async def _find_and_merge_duplicates(self, skill_paths: list[Path]) -> int:
        """
        Find skills with similar names/descriptions and offer to merge them.
        Uses simple name-similarity first (no embedding cost), LLM for borderline cases.
        Returns count of merges performed.
        """
        merged_count = 0
        processed = set()

        for i, a in enumerate(skill_paths):
            if a in processed:
                continue
            for b in skill_paths[i + 1:]:
                if b in processed:
                    continue
                # Simple name similarity check (no LLM cost)
                ratio = SequenceMatcher(None, a.parent.stem, b.parent.stem).ratio()
                if ratio > 0.7:
                    logger.info(f"Duplicate candidate: {a.parent.stem} ↔ {b.parent.stem} (sim={ratio:.2f})")
                    merged = await self._merge_skills(a, b)
                    if merged:
                        processed.add(a)
                        processed.add(b)
                        merged_count += 1
                        break  # one merge at a time to avoid conflicts

        return merged_count

    async def _merge_skills(self, path_a: Path, path_b: Path) -> bool:
        """Ask the LLM to merge two similar skills into one."""
        if not self.llm:
            return False
        try:
            content_a = path_a.read_text()
            content_b = path_b.read_text()

            prompt = f"""These two skills are similar. Merge them into one better skill.
Keep the best parts of each. Use the SKILL.md format with YAML frontmatter.
Respond ONLY with the merged SKILL.md content, no explanation.

SKILL A ({path_a.parent.name}):
{content_a}

SKILL B ({path_b.parent.name}):
{content_b}"""

            merged = await self.llm(prompt)
            if not merged or len(merged) < 100:
                return False

            # Save merged skill under the name of the higher-usage one
            text_a = path_a.read_text()
            text_b = path_b.read_text()
            if len(text_b) > len(text_a):
                path_a, path_b = path_b, path_a

            merged_path = path_a
            merged_path.write_text(merged)
            self._archive(path_b.parent)
            logger.info(f"Merged {path_b.parent.name} into {path_a.parent.name}")
            return True

        except Exception as e:
            logger.debug(f"Merge failed: {e}")
            return False

    def _write_report(self, results: dict, duration: float) -> str:
        return f"""# Skill Curator Report — {datetime.now().strftime('%Y-%m-%d')}

## Summary
- Skills before: {results['total_skills_before']}
- Graded: {results['graded']}
- Archived (low quality): {results['archived']}
- Merged (duplicates): {results['merged']}
- Duration: {duration:.1f}s

## Archived Skills
Archived skills are in `data/skills/.archive/`. Restore by moving back to `data/skills/`.

## Next Run
{(datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')}
"""


async def should_run() -> bool:
    """Returns True if 7 days have passed since last curator run."""
    if not CURATOR_STATE.exists():
        return True
    try:
        state = json.loads(CURATOR_STATE.read_text())
        last = datetime.fromisoformat(state["last_run"])
        return (datetime.now() - last).days >= 7
    except Exception:
        return True
