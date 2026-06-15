"""
SkillImprover — periodic review and improvement of the skill library.

Inspects skill usage metrics (from MetricsCollector), identifies skills that
are unused, underused, or could be merged, and optionally generates improved
versions or prunes stale skills.

This is the "meta-learning" loop: improve the learning system itself.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.core.paths import SKILLS_DIR

logger = logging.getLogger(__name__)

# Minimum usage count before a skill is considered "used"
MIN_USAGE_COUNT = 2

# Age in days before an unused skill is considered stale
STALE_AGE_DAYS = 14


class SkillImprover:
    """Reviews the skill library and recommends or performs improvements.

    Can be called periodically (e.g., every N sessions) or on demand.
    """

    def __init__(self, metrics_collector=None):
        self._metrics = metrics_collector
        self._last_review: Optional[dict] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def review_skills(self, force: bool = False) -> dict:
        """Analyze all skills and return a review report.

        Parameters
        ----------
        force : bool
            If True, skip staleness check and always run.

        Returns
        -------
        dict with keys:
            - total: total skill count
            - used: skills used at least MIN_USAGE_COUNT times
            - unused: skills with zero usage
            - stale: skills unused and older than STALE_AGE_DAYS
            - candidates: skills that could be merged or improved
        """
        skills = self._discover_skills()
        usage = await self._get_usage_stats() if self._metrics else {}

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": len(skills),
            "used": [],
            "unused": [],
            "stale": [],
            "candidates": [],
        }

        for skill in skills:
            name = skill["name"]
            count = usage.get(name, 0)
            skill["usage_count"] = count

            if count >= MIN_USAGE_COUNT:
                report["used"].append(skill)
            else:
                report["unused"].append(skill)
                if self._is_stale(skill):
                    report["stale"].append(skill)
                    skill["reason"] = f"Unused for >{STALE_AGE_DAYS} days"
                else:
                    # Low usage may indicate poor discoverability
                    skill["reason"] = "Low usage count — may need better description"
                    report["candidates"].append(skill)

        self._last_review = report
        logger.info(
            f"Skill review: {report['total']} total, "
            f"{len(report['used'])} used, "
            f"{len(report['unused'])} unused, "
            f"{len(report['stale'])} stale"
        )
        return report

    def prune_stale(self, dry_run: bool = True) -> list[str]:
        """Delete stale skills. Returns names of pruned skills.

        Parameters
        ----------
        dry_run : bool
            If True, only report what would be pruned. If False, actually delete.
        """
        if not self._last_review:
            return []

        pruned = []
        for skill in self._last_review.get("stale", []):
            name = skill["name"]
            skill_dir = SKILLS_DIR / name
            if skill_dir.exists():
                pruned.append(name)
                if not dry_run:
                    import shutil
                    try:
                        shutil.rmtree(str(skill_dir))
                        logger.info(f"Pruned stale skill: {name}")
                    except OSError as e:
                        logger.error(f"Failed to prune skill {name}: {e}")

        return pruned

    def get_improvement_suggestions(self) -> list[dict]:
        """Generate improvement suggestions based on the last review."""
        if not self._last_review:
            return []

        suggestions = []
        for skill in self._last_review.get("candidates", []):
            suggestions.append({
                "name": skill["name"],
                "reason": skill.get("reason", "Unknown"),
                "action": "improve_description",
            })
        return suggestions

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_usage_stats(self) -> dict[str, int]:
        """Query MetricsCollector for skill usage counts."""
        if not self._metrics:
            return {}
        try:
            return await self._metrics.get_skill_usage_counts()
        except Exception as e:
            logger.debug(f"Could not get skill usage: {e}")
            return {}

    def _discover_skills(self) -> list[dict]:
        """List all skills in the skills directory."""
        if not SKILLS_DIR.exists():
            return []
        skills = []
        for entry in sorted(SKILLS_DIR.iterdir()):
            skill_path = entry / "SKILL.md"
            if skill_path.exists():
                content = skill_path.read_text(encoding="utf-8")
                created = self._extract_created(content)
                skills.append({
                    "name": entry.name,
                    "path": str(skill_path),
                    "created": created,
                })
        return skills

    @staticmethod
    def _is_stale(skill: dict) -> bool:
        """Check if a skill is stale based on creation date and usage."""
        created = skill.get("created")
        if not created:
            return False
        try:
            created_dt = datetime.fromisoformat(created)
            # Make timezone-aware if it's naive (so comparison works with utcnow)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - created_dt).days
            return age >= STALE_AGE_DAYS
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _extract_created(content: str) -> Optional[str]:
        """Extract 'created' field from YAML frontmatter."""
        match = re.search(r"^created:\s*(.+)$", content, re.MULTILINE)
        if match:
            return match.group(1).strip().strip('"').strip("'")
        # Fallback: check file modification time
        return None
