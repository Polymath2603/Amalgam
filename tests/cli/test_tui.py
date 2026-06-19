"""
Tests for the Amalgam TUI module (cli/tui.py).

These tests cover the inline dropdown system, command registry,
fuzzy filtering, and full TUI integration via Textual's test pilot.
"""
import sys

import pytest
from cli.tui import InlineDropdown, fuzzy_filter, _init_command_registry, get_slash_commands, _COMMAND_DEFS

try:
    import textual  # noqa: F401
    _HAS_TEXTUAL = True
except ImportError:
    _HAS_TEXTUAL = False


# ── Unit tests (no Textual TUI needed) ─────────────────────────────────


class TestCommandRegistry:
    def test_init_registry_populates_commands(self):
        _COMMAND_DEFS.clear()
        _init_command_registry()
        cmds = get_slash_commands()
        required = [
            "/resume", "/provider", "/model", "/exit", "/help", "/rename",
            "/compact", "/retry", "/cancel", "/think", "/session", "/sessions",
            "/status", "/health", "/crash", "/companion", "/new", "/clear", "/quit",
        ]
        for cmd in required:
            assert cmd in cmds, f"Missing command: {cmd}"
        assert len(cmds) >= 19

    def test_provider_model_have_arg_type(self):
        from cli.tui import _COMMAND_DEFS
        _COMMAND_DEFS.clear()
        from cli.tui import _init_command_registry
        _init_command_registry()
        assert _COMMAND_DEFS["/provider"][2] == ["provider"]
        assert _COMMAND_DEFS["/model"][2] == ["model"]
        assert _COMMAND_DEFS["/help"][2] is None
        # Provider description should mention add|set|rm
        assert "add" in _COMMAND_DEFS["/provider"][0].lower()


class TestFuzzyFilter:
    def test_prefix_matches_first(self):
        from cli.tui import fuzzy_filter
        result = fuzzy_filter("h", ["/crash", "/health", "/help", "/think", "/model"])
        assert result[0:2] == ["/health", "/help"]

    def test_exact_match_first(self):
        from cli.tui import fuzzy_filter
        items = ["/provider", "/model", "/exit", "/help"]
        result = fuzzy_filter("help", items)  # query without /
        assert result[0] == "/help"

    def test_no_match_returns_empty(self):
        from cli.tui import fuzzy_filter
        result = fuzzy_filter("zzz", ["/help", "/exit"])
        assert result == []

    def test_ignores_leading_slash(self):
        from cli.tui import fuzzy_filter
        result = fuzzy_filter("h", ["/health", "/help", "/think"])
        # prefix match: starts with h → /health, /help
        # substring match: contains h → /think
        assert "/health" in result and "/help" in result

    def test_case_insensitive(self):
        from cli.tui import fuzzy_filter
        result = fuzzy_filter("H", ["/health", "/help"])
        assert result == ["/health", "/help"]

    def test_substring_matches(self):
        from cli.tui import fuzzy_filter
        result = fuzzy_filter("rovid", ["/provider", "/help"])
        assert "/provider" in result


class TestDropownWidget:
    def test_select_prev_next(self):
        from cli.tui import InlineDropdown
        dd = InlineDropdown()
        dd.items = [("/help", "help"), ("/health", "health"), ("/exit", "exit")]
        assert dd.selected == 0
        dd.select_next()
        assert dd.selected == 1
        dd.select_next()
        assert dd.selected == 2
        dd.select_next()
        assert dd.selected == 2  # clamps at max (no wrap)
        dd.select_prev()
        assert dd.selected == 1
        dd.select_prev()
        assert dd.selected == 0
        dd.select_prev()
        assert dd.selected == 0  # clamps at 0 (no wrap)
        assert dd.current_value == "/help"

    def test_empty_select_noop(self):
        from cli.tui import InlineDropdown
        dd = InlineDropdown()
        dd.items = []
        dd.select_next()
        assert dd.selected == 0
        assert dd.current_value == ""  # empty string when no items


# ── TUI integration tests (require Textual) ────────────────────────────


class MockSettings:
    """Minimal settings mock with openai + gemini configured."""
    def __init__(self):
        self._data = {
            "provider": {
                "openai": {"api_key": "test-key", "model": "gpt-4o"},
                "gemini": {"api_key": "test-key", "model": "gemini-2.5-flash"},
                "active": "openai",
            }
        }
    def get(self, key, default=""):
        keys = key.split(".")
        val = self._data
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val
    def set(self, key, value):
        keys = key.split(".")
        d = self._data
        for kk in keys[:-1]:
            d = d.setdefault(kk, {})
        d[keys[-1]] = value


class MockMemory:
    def get_current_session(self):
        return "session-1"
    def get_sessions(self):
        return [{"id": "s1", "title": "t1", "message_count": 3}]
    def start_session(self):
        pass
    def get_session_turns(self, sid, limit=5):
        return [{"role": "user", "content": "hello"}]
    def rename_session(self, sid, title):
        return title
    def compact(self):
        pass


class MockAgent:
    async def handle_user_input(self, text):
        for ch in [("__thinking__", "thinking..."),
                   ("__tool__", "tool call"),
                   ("assistant", "Hello!")]:
            yield ch


@pytest.fixture
def tui():
    """Create a TUI app ready for pilot testing.
    
    Requires Textual — tests that use this fixture are auto-skipped
    if the library is missing.
    """
    from cli.tui import AmalgamTUI
    app = AmalgamTUI()
    return app


class TestTUIApp:
    pytestmark = pytest.mark.skipif(
        not _HAS_TEXTUAL,
        reason="Textual not available",
    )
    """Integration tests using Textual's test pilot.
    
    These tests simulate keystrokes and verify that:
    - / opens the command dropdown
    - Typing filters the dropdown
    - Enter autocompletes (does not execute)
    - Space after /provider shows provider arg dropdown
    - Arrow keys navigate the dropdown
    - Esc hides the dropdown
    - Plain Enter executes commands (no dropdown visible)
    """

    @pytest.mark.asyncio
    async def test_command_dropdown_appears_on_slash(self, tui):
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            await pilot.press("/")
            await pilot.pause(0.2)
            assert dd.visible
            assert len(dd.items) >= 19

    @pytest.mark.asyncio
    async def test_enter_autocompletes_command(self, tui):
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            inp = pilot.app.query_one("#chat-input")
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            await pilot.press("/")
            await pilot.pause(0.2)
            first = dd.items[0][0]
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert not dd.visible, "Dropdown hidden after autocomplete"
            assert inp.value == first + " ", f"Input should be {first + ' '!r}, got {inp.value!r}"

    @pytest.mark.asyncio
    async def test_space_after_provider_shows_providers(self, tui):
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            # Type /provider with keystrokes
            await pilot.press("/", "p", "r", "o", "v", "i", "d", "e", "r")
            await pilot.pause(0.2)

            await pilot.press(" ")
            await pilot.pause(0.3)
            assert dd.visible
            # Now shows subcommands [add, set, rm]
            values = [v for v, _ in dd.items]
            assert "add" in values
            assert "set" in values
            assert "rm" in values
            assert len(dd.items) == 3

    @pytest.mark.asyncio
    async def test_enter_autocompletes_provider_arg(self, tui):
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            inp = pilot.app.query_one("#chat-input")
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            # Type /provider + space with keystrokes
            await pilot.press("/", "p", "r", "o", "v", "i", "d", "e", "r", " ")
            await pilot.pause(0.3)
            assert dd.visible
            # First item is now "add"
            assert dd.items[0][0] == "add"
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert not dd.visible, "Dropdown hidden after autocomplete"
            assert inp.value == "/provider add "

    @pytest.mark.asyncio
    async def test_space_after_model_shows_models(self, tui):
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            # Type /model + space with keystrokes
            await pilot.press("/", "m", "o", "d", "e", "l", " ")
            await pilot.pause(0.3)
            assert dd.visible
            # Should show models from both configured providers (openai + gemini)
            assert len(dd.items) >= 4, f"Expected 4+ models, got {len(dd.items)}: {[v for v,_ in dd.items]}"
            values = [v for v, _ in dd.items]
            assert "gpt-4o" in values
            assert "gemini-2.5-flash" in values

    @pytest.mark.asyncio
    async def test_arrow_keys_navigate_dropdown(self, tui):
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            inp = pilot.app.query_one("#chat-input")
            inp.value = ""
            inp.cursor_position = 0
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            await pilot.press("/", "r")
            await pilot.pause(0.2)
            assert dd.visible
            assert len(dd.items) >= 2
            idx0 = dd.selected
            await pilot.press("down")
            await pilot.pause(0.1)
            assert dd.selected == idx0 + 1
            await pilot.press("up")
            await pilot.pause(0.1)
            assert dd.selected == idx0

    @pytest.mark.asyncio
    async def test_esc_hides_dropdown(self, tui):
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            await pilot.press("/")
            await pilot.pause(0.2)
            assert dd.visible
            await pilot.press("escape")
            await pilot.pause(0.2)
            assert not dd.visible

    @pytest.mark.asyncio
    async def test_plain_enter_executes_command(self, tui):
        """With no dropdown visible, Enter should submit the command."""
        async with tui.run_test(size=(120, 40)) as pilot:
            inp = pilot.app.query_one("#chat-input")
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)

            for cmd in ["/help", "/status", "/session"]:
                inp.value = cmd
                inp.cursor_position = len(cmd)
                await pilot.press("enter")
                await pilot.pause(0.1)

    @pytest.mark.asyncio
    async def test_provider_arg_then_enter_executes(self, tui):
        """Typing /provider <name> and pressing Enter (no dropdown) executes."""
        async with tui.run_test(size=(120, 40)) as pilot:
            inp = pilot.app.query_one("#chat-input")
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)

            inp.value = "/provider openai"
            inp.cursor_position = len(inp.value)
            await pilot.press("enter")
            await pilot.pause(0.1)

    @pytest.mark.asyncio
    async def test_model_arg_then_enter_executes(self, tui):
        """Typing /model <name> and pressing Enter (no dropdown) executes."""
        async with tui.run_test(size=(120, 40)) as pilot:
            inp = pilot.app.query_one("#chat-input")
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)

            inp.value = "/model gpt-4o"
            inp.cursor_position = len(inp.value)
            await pilot.press("enter")
            await pilot.pause(0.1)

    @pytest.mark.asyncio
    async def test_provider_add_shows_all_known_providers(self, tui):
        """/provider add <space> shows all KNOWN_PROVIDERS."""
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            # /provider add + space
            for ch in "/provider add ":
                await pilot.press(ch)
            await pilot.pause(0.3)
            assert dd.visible
            values = [v for v, _ in dd.items]
            assert "openai" in values
            assert "gemini" in values
            assert "anthropic" in values
            assert "ollama" in values
            assert len(dd.items) >= 15, f"Expected 15+ known providers, got {len(dd.items)}"

    @pytest.mark.asyncio
    async def test_provider_set_shows_only_configured(self, tui):
        """/provider set <space> shows only providers with API keys."""
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            for ch in "/provider set ":
                await pilot.press(ch)
            await pilot.pause(0.3)
            assert dd.visible
            values = [v for v, _ in dd.items]
            assert "openai" in values
            assert "gemini" in values
            assert "anthropic" not in values  # not configured

    @pytest.mark.asyncio
    async def test_provider_rm_shows_only_configured(self, tui):
        """/provider rm <space> shows only providers with API keys."""
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            for ch in "/provider rm ":
                await pilot.press(ch)
            await pilot.pause(0.3)
            assert dd.visible
            values = [v for v, _ in dd.items]
            assert "openai" in values
            assert "gemini" in values
            assert len(values) == 2, f"Expected exactly 2 configured providers, got {len(values)}"

    @pytest.mark.asyncio
    async def test_provider_add_anthropic_triggers_key_prompt(self, tui):
        """/provider add anthropic + Enter → API key prompt."""
        async with tui.run_test(size=(120, 40)) as pilot:
            settings = MockSettings()
            pilot.app.set_backend(settings, None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            inp = pilot.app.query_one("#chat-input")

            # Type full command via keystrokes
            for ch in "/provider add anthropic":
                await pilot.press(ch)
            await pilot.pause(0.2)

            # Dropdown should be hidden because exact match typed
            dd = pilot.app.query_one("#inline-dropdown")
            assert not dd.visible, "Dropdown should hide on exact provider name match"

            await pilot.press("enter")
            await pilot.pause(0.3)
            assert pilot.app._pending_api_key_for == ("add", "anthropic")
            assert "Enter API key for anthropic" in inp.placeholder

            # Submit the API key
            for ch in "sk-ant-test123":
                await pilot.press(ch)
            await pilot.pause(0.1)
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert pilot.app._pending_api_key_for is None
            assert inp.placeholder == "Type a message…"

    @pytest.mark.asyncio
    async def test_provider_set_key_prompt(self, tui):
        """/provider set openai + Enter → API key prompt (updates existing key)."""
        async with tui.run_test(size=(120, 40)) as pilot:
            settings = MockSettings()
            pilot.app.set_backend(settings, None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            inp = pilot.app.query_one("#chat-input")

            for ch in "/provider set openai":
                await pilot.press(ch)
            await pilot.pause(0.2)
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert pilot.app._pending_api_key_for == ("set", "openai")
            assert "Enter API key for openai" in inp.placeholder

    @pytest.mark.asyncio
    async def test_provider_rm_removes_key(self, tui):
        """/provider rm openai + Enter removes api_key from config."""
        async with tui.run_test(size=(120, 40)) as pilot:
            settings = MockSettings()
            pilot.app.set_backend(settings, None, MockMemory(), MockAgent())
            await pilot.pause(0.3)

            # Verify key exists before rm
            assert settings.get("provider.openai", {}).get("api_key") == "test-key"

            for ch in "/provider rm openai":
                await pilot.press(ch)
            await pilot.pause(0.2)
            await pilot.press("enter")
            await pilot.pause(0.3)

            # Key should be removed from config dict
            cfg = settings.get("provider.openai", {})
            # If cfg is a dict, check api_key removed
            if isinstance(cfg, dict):
                assert "api_key" not in cfg or cfg.get("api_key") == ""

    @pytest.mark.asyncio
    async def test_model_shows_models_from_all_providers(self, tui):
        """/model <space> shows models from ALL configured providers."""
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            for ch in "/model ":
                await pilot.press(ch)
            await pilot.pause(0.3)
            assert dd.visible
            values = [v for v, _ in dd.items]
            # openai models + gemini models
            assert "gpt-4o" in values
            assert "gemini-2.5-flash" in values
            assert len(dd.items) >= 4, f"Expected 4+ models from all providers, got {len(dd.items)}"

    @pytest.mark.asyncio
    async def test_model_exact_match_hides_dropdown(self, tui):
        """Typing an exact model name hides dropdown so Enter executes."""
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            # Clear input, type exact model
            inp = pilot.app.query_one("#chat-input")
            inp.value = ""
            for ch in "/model gpt-4o":
                await pilot.press(ch)
            await pilot.pause(0.2)
            assert not dd.visible, "Dropdown should hide on exact model match"

    @pytest.mark.asyncio
    async def test_enter_on_command_shows_arg_dropdown(self, tui):
        """Enter on /provider in command dropdown shows arg dropdown."""
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            inp = pilot.app.query_one("#chat-input")
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            # Type /provider and Enter to autocomplete
            await pilot.press("/", "p", "r", "o", "v", "i", "d", "e", "r")
            await pilot.pause(0.2)
            assert dd.visible
            await pilot.press("enter")
            await pilot.pause(0.3)
            # Should autocomplete to /provider + space, and show subcommands
            assert inp.value == "/provider ", f"Got {inp.value!r}"
            assert dd.visible, "Arg dropdown should appear after autocomplete"
            values = [v for v, _ in dd.items]
            assert "add" in values
            assert "set" in values

    @pytest.mark.asyncio
    async def test_enter_on_model_shows_model_dropdown(self, tui):
        """Enter on /model in command dropdown shows model dropdown."""
        from cli.tui import InlineDropdown
        async with tui.run_test(size=(120, 40)) as pilot:
            inp = pilot.app.query_one("#chat-input")
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)
            dd = pilot.app.query_one("#inline-dropdown", InlineDropdown)

            # Type /model and Enter to autocomplete
            await pilot.press("/", "m", "o", "d", "e", "l")
            await pilot.pause(0.2)
            assert dd.visible
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert inp.value == "/model ", f"Got {inp.value!r}"
            assert dd.visible, "Model dropdown should appear after autocomplete"
            assert len(dd.items) >= 4, f"Expected 4+ models, got {len(dd.items)}"

    @pytest.mark.asyncio
    async def test_rename_arg_then_enter_executes(self, tui):
        """Typing /rename <name> and pressing Enter executes."""
        async with tui.run_test(size=(120, 40)) as pilot:
            inp = pilot.app.query_one("#chat-input")
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)

            inp.value = "/rename my-test-session"
            inp.cursor_position = len(inp.value)
            await pilot.press("enter")
            await pilot.pause(0.1)

    @pytest.mark.asyncio
    async def test_plain_message_send(self, tui):
        """Typing a normal message and Enter should send it."""
        async with tui.run_test(size=(120, 40)) as pilot:
            inp = pilot.app.query_one("#chat-input")
            pilot.app.set_backend(MockSettings(), None, MockMemory(), MockAgent())
            await pilot.pause(0.3)

            inp.value = "hello world"
            inp.cursor_position = len(inp.value)
            await pilot.press("enter")
            await pilot.pause(0.3)

    @pytest.mark.asyncio
    async def test_exit_command(self, tui):
        """/exit should close the app."""
        async with tui.run_test(size=(120, 40)) as pilot:
            inp = pilot.app.query_one("#chat-input")
            inp.value = "/exit"
            inp.cursor_position = len(inp.value)
            await pilot.press("enter")
            await pilot.pause(0.1)
