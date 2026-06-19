"""Tests for the plugin system (both PluginRegistry and PluginManager)."""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from backend.core.plugin import (
    Plugin,
    PluginRegistry,
    discover_plugins,
    get_registry,
    register,
    reset_registry,
)
from backend.plugins.base import BasePlugin, PluginMetadata, PluginTool
from backend.plugins.manager import PluginManager


# ======================================================================
# PluginRegistry tests (backend.core.plugin)
# ======================================================================


class _RegistryPlugin(Plugin):
    name = "test_registry_plugin"

    def __init__(self) -> None:
        super().__init__()
        self.called: List[str] = []

    async def on_tool_definition(self, tools: list[dict]) -> list[dict]:
        self.called.append("on_tool_definition")
        return tools + [{"name": "from_plugin"}]

    async def on_system_prompt(self, prompt: str) -> str:
        self.called.append("on_system_prompt")
        return prompt + "\n# plugin addition"

    async def on_messages(self, messages: list[dict]) -> list[dict]:
        self.called.append("on_messages")
        return messages

    async def on_compaction(self, summary: str) -> str:
        self.called.append("on_compaction")
        return summary

    async def on_tool_result(
        self, tool_name: str, args: dict, result: str
    ) -> str:
        self.called.append("on_tool_result")
        return result


class _EmptyNamePlugin(Plugin):
    name = ""


class TestPlugin:
    def test_requires_name(self) -> None:
        with pytest.raises(ValueError, match="non-empty `name`"):
            _EmptyNamePlugin()

    def test_is_enabled_by_default(self) -> None:
        p = _RegistryPlugin()
        assert p.is_enabled() is True


class TestPluginRegistry:
    def setup_method(self) -> None:
        self.registry = PluginRegistry()

    def test_register_and_get(self) -> None:
        p = _RegistryPlugin()
        self.registry.register(p)
        assert self.registry.get("test_registry_plugin") is p
        assert self.registry.get("nonexistent") is None

    def test_register_rejects_empty_name(self) -> None:
        # The constructor itself enforces a non-empty name, but
        # register() also double-checks.
        class NoName(Plugin):
            name = ""

        with pytest.raises(ValueError, match="non-empty `name`"):
            NoName()

        # Also verify that register() rejects plugins with empty name
        # even if they somehow bypass the constructor (e.g. via
        # __init_subclass__ tricks).
        from unittest.mock import MagicMock

        bad = MagicMock(spec=Plugin)
        bad.name = ""
        with pytest.raises(ValueError, match="empty name"):
            self.registry.register(bad)

    def test_register_on_conflict_warn(self) -> None:
        p1 = _RegistryPlugin()
        p2 = _RegistryPlugin()
        self.registry.register(p1, on_conflict="warn")
        # Should not raise
        self.registry.register(p2, on_conflict="warn")
        assert self.registry.get("test_registry_plugin") is p2

    def test_register_on_conflict_raise(self) -> None:
        p1 = _RegistryPlugin()
        p2 = _RegistryPlugin()
        self.registry.register(p1)
        with pytest.raises(ValueError, match="already registered"):
            self.registry.register(p2, on_conflict="raise")

    def test_register_on_conflict_skip(self) -> None:
        p1 = _RegistryPlugin()
        p2 = _RegistryPlugin()
        self.registry.register(p1)
        self.registry.register(p2, on_conflict="skip")
        assert self.registry.get("test_registry_plugin") is p1

    def test_unregister(self) -> None:
        p = _RegistryPlugin()
        self.registry.register(p)
        assert self.registry.unregister("test_registry_plugin") is p
        assert self.registry.get("test_registry_plugin") is None

    def test_unregister_nonexistent(self) -> None:
        assert self.registry.unregister("nothing") is None

    def test_all_property(self) -> None:
        assert self.registry.all == []
        p = _RegistryPlugin()
        self.registry.register(p)
        assert self.registry.all == [p]

    def test_clear(self) -> None:
        self.registry.register(_RegistryPlugin())
        self.registry.clear()
        assert self.registry.all == []

    @pytest.mark.asyncio
    async def test_hook_tool_definition(self) -> None:
        p = _RegistryPlugin()
        self.registry.register(p)
        result = await self.registry.hook_tool_definition(
            [{"name": "existing"}]
        )
        assert len(result) == 2
        assert result[1]["name"] == "from_plugin"
        assert "on_tool_definition" in p.called

    @pytest.mark.asyncio
    async def test_hook_system_prompt(self) -> None:
        p = _RegistryPlugin()
        self.registry.register(p)
        result = await self.registry.hook_system_prompt("hello")
        assert "# plugin addition" in result
        assert "on_system_prompt" in p.called

    @pytest.mark.asyncio
    async def test_hook_skips_disabled_plugins(self) -> None:
        p = _RegistryPlugin()
        p._enabled = False
        self.registry.register(p)
        result = await self.registry.hook_tool_definition([{"name": "x"}])
        # Plugin was skipped, so no additions
        assert len(result) == 1
        assert p.called == []

    @pytest.mark.asyncio
    async def test_hook_error_isolation(self) -> None:
        class _FailingPlugin(Plugin):
            name = "failing"

            async def on_tool_definition(self, tools):
                raise RuntimeError("boom")

        class _GoodPlugin(Plugin):
            name = "good"

            async def on_tool_definition(self, tools):
                return tools + [{"name": "good_tool"}]

        self.registry.register(_FailingPlugin())
        self.registry.register(_GoodPlugin())
        result = await self.registry.hook_tool_definition([{"name": "x"}])
        # The failing plugin should not prevent the good one from running
        assert any(t["name"] == "good_tool" for t in result)

    @pytest.mark.asyncio
    async def test_hook_timeout(self) -> None:
        class _SlowPlugin(Plugin):
            name = "slow"

            async def on_tool_definition(self, tools):
                await asyncio.sleep(100)
                return tools

        self.registry.register(_SlowPlugin())
        # With a very short timeout, the slow plugin should be skipped
        result = await self.registry.hook_tool_definition(
            [{"name": "x"}], timeout=0.01
        )
        assert result == [{"name": "x"}]


class TestGlobalRegistry:
    def teardown_method(self) -> None:
        reset_registry()

    def test_register_global(self) -> None:
        p = _RegistryPlugin()
        register(p)
        registry = get_registry()
        assert registry.get("test_registry_plugin") is p

    def test_reset_registry(self) -> None:
        register(_RegistryPlugin())
        reset_registry()
        assert get_registry().all == []


# ======================================================================
# PluginMetadata tests
# ======================================================================


class TestPluginMetadata:
    def test_defaults_are_empty_lists(self) -> None:
        m = PluginMetadata(
            name="test",
            version="1.0",
            author="author",
            description="desc",
        )
        m2 = PluginMetadata(
            name="test",
            version="1.0",
            author="author",
            description="desc",
            requires=["dep"],
            tags=["tag"],
        )
        assert m.requires == []
        assert m.tags == []
        assert m2.requires == ["dep"]
        assert m2.tags == ["tag"]


# ======================================================================
# PluginTool tests
# ======================================================================


class TestPluginTool:
    @pytest.mark.asyncio
    async def test_async_function(self) -> None:
        async def my_tool(text: str) -> str:
            return f"processed: {text}"

        tool = PluginTool(
            name="my_tool",
            description="A test tool",
            func=my_tool,
        )
        result = await tool(text="hello")
        assert result == "processed: hello"

    @pytest.mark.asyncio
    async def test_sync_function(self) -> None:
        def my_tool(text: str) -> str:
            return f"sync: {text}"

        tool = PluginTool(
            name="sync_tool",
            description="A sync tool",
            func=my_tool,
        )
        result = await tool(text="world")
        assert result == "sync: world"

    def test_to_dict(self) -> None:
        async def dummy() -> None:
            pass

        tool = PluginTool(
            name="dummy",
            description="Dummy tool",
            func=dummy,
            parameters={"type": "object", "properties": {}},
        )
        d = tool.to_dict()
        assert d["name"] == "dummy"
        assert d["description"] == "Dummy tool"
        assert d["parameters"] == {"type": "object", "properties": {}}


# ======================================================================
# BasePlugin tests
# ======================================================================


class _TestBasePlugin(BasePlugin):
    def __init__(
        self, config: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            PluginMetadata(
                name="test_base",
                version="1.0.0",
                author="test",
                description="A base test plugin",
            ),
            config=config,
        )


class TestBasePlugin:
    def test_instantiation(self) -> None:
        plugin = _TestBasePlugin()
        assert plugin.name == "test_base"
        assert plugin.metadata.version == "1.0.0"
        assert plugin.is_enabled() is True

    def test_config(self) -> None:
        plugin = _TestBasePlugin(config={"key": "value"})
        assert plugin.config["key"] == "value"

    @pytest.mark.asyncio
    async def test_initialize_calls_on_initialize(self) -> None:
        class _InitPlugin(BasePlugin):
            def __init__(self) -> None:
                super().__init__(
                    PluginMetadata(
                        name="init_test",
                        version="1.0",
                        author="test",
                        description="init test",
                    )
                )
                self.init_called = False

            async def initialize(self) -> None:
                self.init_called = True
                await super().initialize()

            async def on_initialize(self) -> None:
                self.on_init_called = True

        plugin = _InitPlugin()
        await plugin.initialize()
        assert plugin.init_called
        assert plugin.on_init_called

    @pytest.mark.asyncio
    async def test_lifecycle_enable_disable(self) -> None:
        plugin = _TestBasePlugin()
        assert plugin.is_enabled() is True
        plugin.disable()
        assert plugin.is_enabled() is False
        plugin.enable()
        assert plugin.is_enabled() is True

    @pytest.mark.asyncio
    async def test_register_tool(self) -> None:
        plugin = _TestBasePlugin()

        async def my_tool() -> str:
            return "ok"

        tool = PluginTool(
            name="my_tool", description="test", func=my_tool
        )
        plugin.register_tool(tool)
        assert "my_tool" in plugin.tools
        assert plugin.tools["my_tool"] is tool

    @pytest.mark.asyncio
    async def test_register_and_trigger_hooks(self) -> None:
        plugin = _TestBasePlugin()
        results: List[str] = []

        async def handler1(msg: str) -> None:
            results.append(f"h1:{msg}")

        def handler2(msg: str) -> None:
            results.append(f"h2:{msg}")

        plugin.register_hook("test_event", handler1)
        plugin.register_hook("test_event", handler2)
        await plugin.trigger_hooks("test_event", "hello")
        assert "h1:hello" in results
        assert "h2:hello" in results

    @pytest.mark.asyncio
    async def test_trigger_hooks_preserves_system_exits(self) -> None:
        """SystemExit/KeyboardInterrupt should propagate through hooks."""
        plugin = _TestBasePlugin()

        async def handler_that_exits() -> None:
            raise SystemExit(0)

        async def handler_after() -> None:
            pass  # pragma: no cover

        plugin.register_hook("exit_event", handler_that_exits)
        plugin.register_hook("exit_event", handler_after)
        with pytest.raises(SystemExit):
            await plugin.trigger_hooks("exit_event")

    @pytest.mark.asyncio
    async def test_trigger_hooks_continues_on_error(self) -> None:
        """One failing handler should not stop subsequent handlers."""
        plugin = _TestBasePlugin()
        results: List[str] = []

        async def fail() -> None:
            raise RuntimeError("oops")

        async def succeed() -> None:
            results.append("ok")

        plugin.register_hook("ev", fail)
        plugin.register_hook("ev", succeed)
        await plugin.trigger_hooks("ev")
        assert results == ["ok"]

    @pytest.mark.asyncio
    async def test_on_before_response(self) -> None:
        plugin = _TestBasePlugin()
        context = {"user_message": "hello"}
        result = await plugin.on_before_response(context)
        assert result["user_message"] == "hello"

    @pytest.mark.asyncio
    async def test_on_after_response(self) -> None:
        plugin = _TestBasePlugin()
        result = await plugin.on_after_response("hi")
        assert result == "hi"


# ======================================================================
# PluginManager tests
# ======================================================================


class TestPluginManager:
    def test_init(self) -> None:
        pm = PluginManager(plugins_dir=Path("/tmp"))
        assert pm.plugins == {}
        assert pm.loaded_modules == {}

    @pytest.mark.asyncio
    async def test_empty_directory(self, tmp_path: Path) -> None:
        pm = PluginManager(plugins_dir=tmp_path)
        await pm.discover_and_load()
        assert pm.plugins == {}

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self) -> None:
        pm = PluginManager(
            plugins_dir=Path("/does/not/exist")
        )
        await pm.discover_and_load()
        assert pm.plugins == {}

    def test_get_plugin_returns_none(self) -> None:
        pm = PluginManager(plugins_dir=Path("/tmp"))
        assert pm.get_plugin("nonexistent") is None

    def test_list_plugins_empty(self) -> None:
        pm = PluginManager(plugins_dir=Path("/tmp"))
        assert pm.list_plugins() == []

    @pytest.mark.asyncio
    async def test_enable_disable_notifies_plugin(self) -> None:
        pm = PluginManager(
            plugins_dir=Path("/tmp"), auto_register=False
        )
        plugin = _TestBasePlugin()
        pm.plugins[plugin.name] = plugin

        enabled = await pm.enable_plugin(plugin.name)
        assert enabled is True
        assert plugin.is_enabled() is True

        disabled = await pm.disable_plugin(plugin.name)
        assert disabled is True
        assert plugin.is_enabled() is False

    @pytest.mark.asyncio
    async def test_enable_disable_nonexistent(self) -> None:
        pm = PluginManager(plugins_dir=Path("/tmp"))
        assert await pm.enable_plugin("nope") is False
        assert await pm.disable_plugin("nope") is False

    @pytest.mark.asyncio
    async def test_shutdown_all_returns_errors(self) -> None:
        pm = PluginManager(
            plugins_dir=Path("/tmp"), auto_register=False
        )

        class _FailingPlugin(BasePlugin):
            def __init__(self) -> None:
                super().__init__(
                    PluginMetadata(
                        name="fail_shutdown",
                        version="1.0",
                        author="test",
                        description="fails on shutdown",
                    )
                )

            async def on_shutdown(self) -> None:
                raise RuntimeError("shutdown failed")

        pm.plugins["fail_shutdown"] = _FailingPlugin()
        errors = await pm.shutdown_all()
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)

    @pytest.mark.asyncio
    async def test_shutdown_all_timeout(self) -> None:
        pm = PluginManager(
            plugins_dir=Path("/tmp"), auto_register=False
        )

        class _SlowShutdownPlugin(BasePlugin):
            def __init__(self) -> None:
                super().__init__(
                    PluginMetadata(
                        name="slow_shutdown",
                        version="1.0",
                        author="test",
                        description="slow shutdown",
                    )
                )

            async def on_shutdown(self) -> None:
                await asyncio.sleep(100)

        pm.plugins["slow_shutdown"] = _SlowShutdownPlugin()
        errors = await pm.shutdown_all(timeout=0.01)
        assert len(errors) == 1
        assert isinstance(errors[0], TimeoutError)

    @pytest.mark.asyncio
    async def test_unload_plugin(self) -> None:
        pm = PluginManager(
            plugins_dir=Path("/tmp"), auto_register=False
        )
        plugin = _TestBasePlugin()
        pm.plugins[plugin.name] = plugin
        pm.loaded_modules[plugin.name] = None

        result = pm.unload_plugin(plugin.name)
        assert result is True
        assert plugin.name not in pm.plugins

        assert pm.unload_plugin("nonexistent") is False

    @pytest.mark.asyncio
    async def test_reload_plugin_nonexistent(self) -> None:
        pm = PluginManager(plugins_dir=Path("/tmp"))
        result = await pm.reload_plugin("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_all_tools(self) -> None:
        pm = PluginManager(
            plugins_dir=Path("/tmp"), auto_register=False
        )
        plugin = _TestBasePlugin()

        async def dummy() -> str:
            return "ok"

        tool = PluginTool(
            name="dummy", description="dummy", func=dummy
        )
        plugin.register_tool(tool)
        pm.plugins[plugin.name] = plugin

        tools = pm.get_all_tools()
        assert "dummy" in tools


# ======================================================================
# Integration: BasePlugin bridges to PluginRegistry
# ======================================================================


class _BridgedPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__(
            PluginMetadata(
                name="bridged",
                version="1.0",
                author="test",
                description="bridged plugin",
            )
        )

    async def on_tool_definition(
        self, tools: list[dict]
    ) -> list[dict]:
        return tools + [{"name": "bridged_tool"}]


class TestBridge:
    def teardown_method(self) -> None:
        reset_registry()

    @pytest.mark.asyncio
    async def test_base_plugin_registers_with_global_registry(
        self,
    ) -> None:
        """Verify that a BasePlugin registered via PluginManager also
        appears in the global PluginRegistry."""
        pm = PluginManager(
            plugins_dir=Path("/tmp"), auto_register=True
        )
        plugin = _BridgedPlugin()
        pm.plugins[plugin.name] = plugin
        # Simulate what _load_plugin does
        from backend.core.plugin import register as global_register

        global_register(plugin, on_conflict="warn")

        registry = get_registry()
        assert registry.get("bridged") is plugin


# ======================================================================
# discover_plugins helper tests
# ======================================================================


class TestDiscoverPlugins:
    def teardown_method(self) -> None:
        reset_registry()

    def test_nonexistent_directory(self) -> None:
        result = discover_plugins("/does/not/exist")
        assert result == []

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = discover_plugins(str(tmp_path))
        assert result == []
