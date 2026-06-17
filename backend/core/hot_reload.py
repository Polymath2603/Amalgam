"""
Hot-reload — watches data/ directories and reloads components without restart.

Watched: data/skills/, data/agents/, data/characters/, data/constitution.md
NOT watched: backend/ Python files (require restart).

Uses asyncio polling (2s interval) — no watchdog or inotify dependency,
so it works on Android/Termux where native file watchers may be unavailable.

Source: jcode's self-modification feature.
"""

import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SKILLS_DIR = Path("data/skills")
CHARACTERS_DIR = Path("data/characters")
CONSTITUTION_PATH = Path("data/constitution.md")
AGENTS_DIR = Path("data/agents")


class HotReloader:
    """
    File system watcher using asyncio polling (no watchdog dependency).
    Checks every 2 seconds. Low overhead, no native dependencies.
    """

    def __init__(self):
        self._handlers: dict[Path, list[Callable]] = {}
        self._mtimes: dict[Path, float] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def watch(self, path: Path, handler: Callable[[Path], None]):
        """
        Register a handler for a path (file or directory).
        handler(changed_path) is called when the file/any file in dir changes.
        """
        if path not in self._handlers:
            self._handlers[path] = []
        self._handlers[path].append(handler)
        # Record initial mtime
        self._record_mtimes(path)
        logger.debug(f"HotReload: watching {path}")

    def _record_mtimes(self, path: Path):
        if path.is_file():
            self._mtimes[path] = path.stat().st_mtime if path.exists() else 0
        elif path.is_dir():
            for pattern in ("*.md", "*.yaml", "*.yml"):
                for f in path.glob(pattern):
                    self._mtimes[f] = f.stat().st_mtime

    async def start(self):
        """Start the polling loop. Returns immediately (runs in background)."""
        self._running = True
        logger.info("HotReload: started (poll interval=2s)")
        while self._running:
            await asyncio.sleep(2)
            self._check_changes()

    def stop(self):
        """Stop the polling loop."""
        self._running = False
        logger.info("HotReload: stopped")

    def _check_changes(self):
        for watch_path, handlers in self._handlers.items():
            if watch_path.is_file():
                self._check_file(watch_path, handlers)
            elif watch_path.is_dir():
                for pattern in ("*.md", "*.yaml", "*.yml"):
                    for f in list(watch_path.glob(pattern)):
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


# ---------------------------------------------------------------------------
# Singleton + setup
# ---------------------------------------------------------------------------

_reloader = HotReloader()


def get_reloader() -> HotReloader:
    """Get the module-level HotReloader singleton."""
    return _reloader


def setup_hot_reload():
    """
    Wire all hot-reload handlers. Call once at startup.
    Returns the reloader instance (call .start() to begin polling).
    """
    from backend.skills.md_skill import get_loader

    # Skills
    if SKILLS_DIR.exists():
        _reloader.watch(
            SKILLS_DIR,
            lambda p: _reload_skill(p),
        )

    # Constitution
    if CONSTITUTION_PATH.exists():
        _reloader.watch(
            CONSTITUTION_PATH,
            lambda p: _reload_constitution(),
        )

    # Characters
    if CHARACTERS_DIR.exists():
        _reloader.watch(
            CHARACTERS_DIR,
            lambda p: _reload_character(p),
        )

    return _reloader


def _reload_skill(path: Path):
    """Reload all skills when a SKILL.md changes."""
    from backend.skills.md_skill import get_loader
    loader = get_loader()
    if loader:
        loader.load_all()
        logger.info(f"[HotReload] Skills reloaded (triggered by: {path.name})")


def _reload_constitution():
    """Invalidate constitution cache — next call re-reads the file."""
    from backend.core.constitution import reload_constitution
    reload_constitution()
    logger.info("[HotReload] Constitution reloaded")


def _reload_character(path: Path):
    """Log character changes (reload happens on next session)."""
    logger.info(f"[HotReload] Character file changed: {path.name} — will reload on next session")
