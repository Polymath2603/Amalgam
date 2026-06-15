"""Tests for the plugin manager."""

import pytest
from pathlib import Path
from backend.plugins.manager import PluginManager
from backend.plugins.base import BasePlugin, PluginMetadata


class TestPluginManager:
    def test_init(self):
        pm = PluginManager(plugins_dir=Path("/tmp"))
        assert pm.plugins == {}
        assert pm.loaded_modules == {}

    def test_empty_directory(self, tmp_path):
        pm = PluginManager(plugins_dir=tmp_path)
        import asyncio
        asyncio.run(pm.discover_and_load())
        assert pm.plugins == {}

    def test_nonexistent_directory(self):
        pm = PluginManager(plugins_dir=Path("/does/not/exist"))
        import asyncio
        asyncio.run(pm.discover_and_load())
        assert pm.plugins == {}

    def test_get_plugin_returns_none(self):
        pm = PluginManager(plugins_dir=Path("/tmp"))
        assert pm.get_plugin("nonexistent") is None

    def test_list_plugins_empty(self):
        pm = PluginManager(plugins_dir=Path("/tmp"))
        assert pm.list_plugins() == []


class _TestPluginImpl(BasePlugin):
    def __init__(self):
        super().__init__(PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            author="test",
            description="A test plugin",
        ))


class TestBasePlugin:
    def test_base_plugin_instantiation(self):
        plugin = _TestPluginImpl()
        assert plugin.name == "test_plugin"
        assert plugin.metadata.version == "1.0.0"
        assert plugin.metadata.name == "test_plugin"
        assert plugin.metadata.description == "A test plugin"

    def test_base_plugin_lifecycle(self):
        class LifecyclePlugin(BasePlugin):
            def __init__(self):
                super().__init__(PluginMetadata(
                    name="lifecycle",
                    version="1.0",
                    author="test",
                    description="lifecycle test",
                ))
                self._initialized = False
                self._shutdown = False

            async def initialize(self):
                self._initialized = True

            async def shutdown(self):
                self._shutdown = True

        import asyncio
        plugin = LifecyclePlugin()
        asyncio.run(plugin.initialize())
        assert plugin._initialized
        asyncio.run(plugin.shutdown())
        assert plugin._shutdown
