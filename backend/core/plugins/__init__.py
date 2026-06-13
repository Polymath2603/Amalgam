"""Plugin system — load and manage optional feature extensions."""

from typing import Any, Dict, List, Optional
import importlib
import logging
import os

logger = logging.getLogger(__name__)

_plugins: Dict[str, Any] = {}


def load_plugins(plugin_dir: str = None) -> Dict[str, Any]:
    """Discover and load all plugin modules.

    Each plugin module should expose ``register()`` returning a dict with
    keys ``name``, ``hooks`` (list of hook names), and optionally ``init``.
    """
    if plugin_dir is None:
        plugin_dir = os.path.join(os.path.dirname(__file__))

    for fname in sorted(os.listdir(plugin_dir)):
        if fname.startswith("_") or not fname.endswith(".py"):
            continue
        mod_name = fname[:-3]
        try:
            mod = importlib.import_module(f"backend.core.plugins.{mod_name}")
            if hasattr(mod, "register"):
                info = mod.register()
                _plugins[info["name"]] = {"module": mod, "info": info}
                logger.info("Loaded plugin: %s", info["name"])
        except Exception as e:
            logger.error("Failed to load plugin %s: %s", mod_name, e)

    return _plugins


def get_plugin(name: str):
    return _plugins.get(name)


def list_plugins() -> List[str]:
    return list(_plugins.keys())


def reload_plugins():
    _plugins.clear()
    return load_plugins()
