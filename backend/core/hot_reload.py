"""
Watches data/ directories for file changes and reloads affected components.
Source: jcode's self-modification feature — agent edits skills, changes take effect immediately.

Watched: data/skills/, data/agents/, data/characters/, data/constitution.md
NOT watched: backend/ Python files (require explicit approval + restart).

Usage: HotReloader is started in FastAPI lifespan and stopped on shutdown.
"""
import asyncio
import logging
from pathlib import Path
from typing import Callable

from backend.core.paths import DATA_DIR

logger = logging.getLogger(__name__)


class HotReloader:
    """
    File system watcher using asyncio polling (no watchdog dependency).
    Checks every 2 seconds. Low overhead, no native dependencies.
    """

    def __init__(self):
        self._handlers: dict[Path, list[Callable]] = {}
        self._mtimes: dict[Path, float] = {}
        self._running = False

    def watch(self, path: Path, handler: Callable[[Path], None]):
        if path not in self._handlers:
            self._handlers[path] = []
        self._handlers[path].append(handler)
        self._record_mtimes(path)

    def _record_mtimes(self, path: Path):
        if path.is_file():
            self._mtimes[path] = path.stat().st_mtime if path.exists() else 0
        elif path.is_dir():
            for f in path.glob("*.md"):
                self._mtimes[f] = f.stat().st_mtime
            for f in path.glob("*.yaml"):
                self._mtimes[f] = f.stat().st_mtime

    async def start(self):
        self._running = True
        while self._running:
            await asyncio.sleep(2)
            self._check_changes()

    def stop(self):
        self._running = False

    def _check_changes(self):
        for watch_path, handlers in self._handlers.items():
            if watch_path.is_file():
                self._check_file(watch_path, handlers)
            elif watch_path.is_dir():
                for f in list(watch_path.glob("*.md")) + list(watch_path.glob("*.yaml")):
                    self._check_file(f, handlers)

    def _check_file(self, path: Path, handlers: list[Callable]):
        if not path.exists():
            return
        mtime = path.stat().st_mtime
        if self._mtimes.get(path) != mtime:
            self._mtimes[path] = mtime
            logger.info(f"[HotReload] Changed: {path.name}")
            for h in handlers:
                try:
                    h(path)
                except Exception as e:
                    logger.warning(f"Hot-reload handler error for {path}: {e}")


# Module-level singleton
_reloader = HotReloader()


def get_reloader():
    """Return the module-level HotReloader singleton."""
    return _reloader


def setup_hot_reload(skill_loader, constitution):
    """
    Wire all hot-reload handlers. Call once at startup.
    skill_loader: MDSkillLoader instance
    constitution: module with reload_cache() function
    """

    # Skills
    _reloader.watch(
        DATA_DIR / "skills",
        lambda p: _reload_skill(p, skill_loader),
    )

    # Constitution
    _reloader.watch(
        DATA_DIR / "constitution.md",
        lambda p: _reload_constitution(constitution),
    )

    # Characters
    _reloader.watch(
        DATA_DIR / "characters",
        lambda p: _reload_character(p),
    )

    return _reloader


def _reload_skill(path: Path, loader):
    skill = loader._load(path)
    if skill:
        loader.skills = [s for s in loader.skills if s.name != skill.name]
        loader.skills.append(skill)
        logger.info(f"[HotReload] Skill reloaded: {skill.name}")


def _reload_constitution(constitution_module):
    if hasattr(constitution_module, 'reload_cache'):
        constitution_module.reload_cache()
    logger.info("[HotReload] Constitution reloaded")


def _reload_character(path: Path):
    logger.info(f"[HotReload] Character file changed: {path.name} — reload on next session")
