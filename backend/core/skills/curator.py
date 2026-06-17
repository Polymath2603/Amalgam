"""
Autonomous skill curator. Runs weekly as a background asyncio task.
Source: Hermes-Agent's Autonomous Curator — prevents skill rot.

Schedule: run every 7 days. First run: 7 days after first skill is created.
Output: archives bad skills, merges duplicates, writes vault report.

To trigger manually: python -m backend curate
"""
import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path("data/skills")
ARCHIVE_DIR = Path("data/skills/.archive")
VAULT_DIR = Path("data/vault")
CURATOR_STATE = Path("data/skills/.curator_state.json")

MIN_USAGE = 1
STALE_DAYS = 30


class SkillCurator:
    """
    Grades, merges, and archives skills based on usage data from metrics.db.
    """

    def __init__(self, metrics_collector, llm_caller):
        self.metrics = metrics_collector
        self.llm = llm_caller

    async def run(self):
        """Full curation cycle. Takes 30-120 seconds. Run in background."""
        logger.info("Skill curator starting")
        start = datetime.now()

        skill_files = list(SKILLS_DIR.glob("*.md"))
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
            age_days = (datetime.now() - datetime.fromtimestamp(
                skill_path.stat().st_mtime
            )).days

            grade = self._grade(skill_usage, age_days)
            results["graded"] += 1

            if grade < 0.2:
                self._archive(skill_path)
                results["archived"] += 1
                logger.info(f"Archived: {name} (grade={grade:.2f})")
            else:
                surviving.append(skill_path)

        # Step 2: Find and merge semantic duplicates
        if len(surviving) >= 2:
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
        Grade a skill 0.0-1.0 based on usage and freshness.
        0.0 = should be archived. 1.0 = excellent, keep.

        Formula: usage score (0-0.7) + freshness score (0-0.3)
        """
        import math
        usage_score = min(0.7, 0.35 * math.log1p(usage_count))
        freshness = max(0.0, 1.0 - (age_days / STALE_DAYS)) * 0.3
        return usage_score + freshness

    def _archive(self, path: Path):
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        dest = ARCHIVE_DIR / path.name
        shutil.move(str(path), str(dest))

    async def _get_usage_stats(self) -> dict[str, int]:
        try:
            report = await self.metrics.report(days=30)
            return {s["skill_used"]: s["uses"] for s in report.get("top_skills", [])}
        except Exception:
            return {}

    async def _find_and_merge_duplicates(self, skill_paths: list[Path]) -> int:
        from difflib import SequenceMatcher
        merged_count = 0
        processed = set()

        for i, a in enumerate(skill_paths):
            if a in processed:
                continue
            for b in skill_paths[i+1:]:
                if b in processed:
                    continue
                ratio = SequenceMatcher(None, a.stem, b.stem).ratio()
                if ratio > 0.7:
                    logger.info(f"Duplicate candidate: {a.stem} <-> {b.stem} (sim={ratio:.2f})")
                    merged = await self._merge_skills(a, b)
                    if merged:
                        processed.add(a)
                        processed.add(b)
                        merged_count += 1
                        break

        return merged_count

    async def _merge_skills(self, path_a: Path, path_b: Path) -> bool:
        try:
            content_a = path_a.read_text()
            content_b = path_b.read_text()

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
            merged_path.write_text(merged)
            self._archive(path_b)
            logger.info(f"Merged {path_b.name} into {path_a.name}")
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
