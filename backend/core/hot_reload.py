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
from typing import Callable, Optional

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
        self._cached_files: dict[Path, list[Path]] = {}  # 28.1: cache file list
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
            files = list(path.glob("*.md")) + list(path.glob("*.yaml"))
            self._cached_files[path] = files  # 28.1: cache file list
            for f in files:
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
                # Use cached file list and re-scan only when needed
                cached = self._cached_files.get(watch_path)
                if cached is None:
                    cached = []
                for f in cached:
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

    # Skills (28.3: capture skill_loader by value via default arg)
    _reloader.watch(
        DATA_DIR / "skills",
        lambda p, loader=skill_loader: _reload_skill(p, loader),
    )

    # Constitution
    _reloader.watch(
        DATA_DIR / "constitution.md",
        lambda p, mod=constitution: _reload_constitution(mod),
    )

    # Characters
    _reloader.watch(
        DATA_DIR / "characters",
        lambda p: _reload_character(p),
    )

    return _reloader


def _reload_skill(path: Path, loader):
    # 28.2: use public load_file method instead of loader._load
    skill = loader.load_file(path)
    if skill:
        logger.info(f"[HotReload] Skill reloaded: {skill.name}")


def _reload_constitution(constitution_module):
    if hasattr(constitution_module, 'reload_cache'):
        constitution_module.reload_cache()
    logger.info("[HotReload] Constitution reloaded")


def _reload_character(path: Path):
    logger.info(f"[HotReload] Character file changed: {path.name} — reload on next session")
