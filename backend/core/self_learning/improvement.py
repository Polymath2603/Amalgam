"""
SkillImprover — periodic review and improvement of the skill library.

Inspects skill usage metrics (from MetricsCollector), identifies skills that
are unused, underused, or could be merged, and optionally generates improved
versions or prunes stale skills.

This is the "meta-learning" loop: improve the learning system itself.
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from backend.core.paths import SKILLS_DIR

logger = logging.getLogger(__name__)

# Minimum usage count before a skill is considered "used"
# Configurable via AMALGAM_SKILL_MIN_USAGE env var
_MIN_USAGE_COUNT_ENV = "AMALGAM_SKILL_MIN_USAGE"
MIN_USAGE_COUNT = int(os.environ.get(_MIN_USAGE_COUNT_ENV, "2"))

# Age in days before an unused skill is considered stale
# Configurable via AMALGAM_SKILL_STALE_DAYS env var
_STALE_AGE_DAYS_ENV = "AMALGAM_SKILL_STALE_DAYS"
STALE_AGE_DAYS = int(os.environ.get(_STALE_AGE_DAYS_ENV, "14"))


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

    async def review_skills(self) -> dict:
        """Analyze all skills and return a review report.

        Returns
        -------
        dict with keys:
            - total: total skill count
            - used: skills used at least MIN_USAGE_COUNT times
            - underused: skills with usage < MIN_USAGE_COUNT (naming reflects actual state)
            - stale: skills unused and older than STALE_AGE_DAYS
            - candidates: skills that could be merged or improved
        """
        skills = self._discover_skills()
        usage = await self._get_usage_stats() if self._metrics else {}

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": len(skills),
            "used": [],
            "underused": [],
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
                report["underused"].append(skill)
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
            f"{len(report['underused'])} underused, "
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
            # Check existence defensively (could race with deletion)
            if not skill_dir.exists():
                continue
            try:
                pruned.append(name)
                if not dry_run:
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
        """List all skills in the skills directory.

        Only reads the first ~512 bytes of each SKILL.md to extract
        the created timestamp, reducing I/O overhead for large skill libraries.
        """
        if not SKILLS_DIR.exists():
            return []
        skills = []
        for entry in sorted(SKILLS_DIR.iterdir()):
            skill_path = entry / "SKILL.md"
            if skill_path.exists():
                try:
                    # Read only frontmatter (first ~512 bytes) instead of full content
                    head = skill_path.read_bytes()[:512]
                    created = self._extract_created(head)
                    skills.append({
                        "name": entry.name,
                        "path": str(skill_path),
                        "created": created,
                    })
                except (OSError, PermissionError) as e:
                    logger.warning(f"Could not read skill {entry.name}: {e}")
                    continue
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
    def _extract_created(content: "str | bytes") -> Optional[str]:
        """Extract 'created' field from YAML frontmatter using safe YAML parsing.

        Reads the frontmatter between '---' delimiters.
        Falls back to regex if YAML parsing fails.
        """
        if isinstance(content, bytes):
            text = content.decode("utf-8", errors="replace")
        else:
            text = content
        # Find YAML frontmatter between --- markers
        if not text.startswith("---"):
            return None
        end_idx = text.find("---", 3)
        if end_idx == -1:
            return None
        frontmatter = text[3:end_idx].strip()
        if not frontmatter:
            return None
        # Try YAML parsing first
        try:
            data = yaml.safe_load(frontmatter)
            if isinstance(data, dict):
                created = data.get("created")
                if created:
                    if isinstance(created, datetime):
                        return created.isoformat()
                    return str(created)
        except yaml.YAMLError:
            pass
        # Fallback to regex
        match = re.search(r"^created:\s*(.+)$", frontmatter, re.MULTILINE)
        if match:
            return match.group(1).strip().strip('"').strip("'")
        return None
