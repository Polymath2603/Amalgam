"""
Tests for the Amalgam CLI sub-modules and __init__.
"""
import json
import os
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def mock_settings():
    """Returns a mock Settings-like object."""
    s = MagicMock()
    s.data = {
        "provider": {
            "active": "gemini",
            "gemini": {"api_key": "test-key", "model": "gemini-2.5-flash", "base_url": "https://generativelanguage.googleapis.com/v1beta"},
            "openai": {"api_key": "", "model": "gpt-4o-mini", "base_url": ""},
            "anthropic": {"api_key: "REDACTED", "base_url": ""},
        },
    }

    def get(dotpath, default=None):
        keys = dotpath.split(".")
        val = s.data
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def set(dotpath, value, fire_callbacks=True):
        keys = dotpath.split(".")
        d = s.data
        for k in keys[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value

    s.get = get
    s.set = set
    s.get_all = lambda: s.data
    return s


# ═════════════════════════════════════════════════════════════════════
# Tests: output.py
# ═════════════════════════════════════════════════════════════════════


class TestOutput:
    def test_set_output_format(self):
        from cli.output import set_output_format, get_output_format, OutputFormat
        set_output_format("json")
        assert get_output_format() == OutputFormat.JSON
        set_output_format("human")
        assert get_output_format() == OutputFormat.HUMAN
        set_output_format(OutputFormat.NDJSON)
        assert get_output_format() == OutputFormat.NDJSON

    def test_wants_human_json(self):
        from cli.output import set_output_format, wants_human, wants_json
        set_output_format("human")
        assert wants_human()
        assert not wants_json()
        set_output_format("json")
        assert not wants_human()
        assert wants_json()

    def test_json_output_does_not_crash(self, capsys):
        """JSON output functions should write valid JSON and not crash."""
        from cli.output import set_output_format
        set_output_format("json")

        from cli.output import banner, message, error, table, panel, markup

        # These should emit JSON to stdout without crashing
        banner("sess-id", "gemini", "gpt-4o")
        message("Hello")
        error("Something broke", title="Oops", hint="Try again")
        table([("a", "1"), ("b", "2")], headers=["Key", "Value"])
        panel("Content", "Panel Title")
        markup("Some markup")

        captured = capsys.readouterr()
        # Should have produced at least 6 lines of JSON
        lines = [l for l in captured.out.strip().split("\n") if l]
        assert len(lines) >= 6
        # All lines should be valid JSON
        for line in lines:
            obj = json.loads(line)
            assert "type" in obj

    def test_set_output_format_invalid(self):
        from cli.output import set_output_format, get_output_format, OutputFormat
        with pytest.raises(ValueError):
            set_output_format("invalid_format")


# ═════════════════════════════════════════════════════════════════════
# Tests: provider.py
# ═════════════════════════════════════════════════════════════════════


class TestProvider:
    def test_known_providers_list(self):
        from cli.provider import KNOWN_PROVIDERS
        assert "gemini" in KNOWN_PROVIDERS
        assert "openai" in KNOWN_PROVIDERS
        assert len(KNOWN_PROVIDERS) > 10

    def test_provider_models_dict(self):
        from cli.provider import PROVIDER_MODELS
        assert "gemini" in PROVIDER_MODELS
        assert "gpt-4o-mini" in PROVIDER_MODELS.get("openai", [])
        assert PROVIDER_MODELS.get("ollama", []) == []

    def test_detect_providers_calls_settings(self, mock_settings):
        from cli.provider import detect_providers
        providers = detect_providers(mock_settings)
        # Should return one entry per known provider
        from cli.provider import KNOWN_PROVIDERS
        assert len(providers) == len(KNOWN_PROVIDERS)

        # Find gemini (has key)
        gemini = [p for p in providers if p.name == "gemini"][0]
        assert gemini.has_api_key
        assert gemini.model == "gemini-2.5-flash"

        # Find openai (no key)
        openai = [p for p in providers if p.name == "openai"][0]
        assert not openai.has_api_key

    @patch.dict(os.environ, {"OPENAI_API_KEY": "env-key-test"}, clear=True)
    def test_detect_providers_with_env(self, mock_settings):
        from cli.provider import detect_providers
        # Settings has empty openai key
        providers = detect_providers(mock_settings)
        openai = [p for p in providers if p.name == "openai"][0]
        assert openai.has_api_key
        assert openai.source == "env"

    def test_resolve_display_name(self):
        from cli.provider import resolve_display_name
        assert resolve_display_name("gemini") == "Google Gemini"
        assert resolve_display_name("openai") == "OpenAI"
        assert resolve_display_name("not_a_provider") == "Not_A_Provider"

    def test_autocomplete_words(self, mock_settings):
        from cli.provider import autocomplete_words
        words = autocomplete_words(mock_settings)
        assert "gemini" in words
        assert "gpt-4o-mini" in words


# ═════════════════════════════════════════════════════════════════════
# Tests: server.py
# ═════════════════════════════════════════════════════════════════════


class TestServer:
    def test_pid_file_operations(self):
        from cli.server import _write_pid, _read_pid, _clear_pid, _ensure_daemon_dir

        with tempfile.TemporaryDirectory() as tmp:
            with patch("cli.server.DAEMON_DIR", tmp):
                with patch("cli.server.PID_FILE", os.path.join(tmp, "daemon.pid")):
                    _ensure_daemon_dir()
                    assert not _read_pid()
                    _write_pid(12345)
                    assert _read_pid() == 12345
                    _clear_pid()
                    assert not _read_pid()

    def test_is_running(self):
        from cli.server import _is_running
        # This process should be running
        assert _is_running(os.getpid())
        # PID 99999999 should not be running
        assert not _is_running(99999999)

    def test_tcp_probe(self):
        from cli.server import _tcp_probe
        # Localhost should have something on at least one common port
        # Just verify it doesn't crash and returns bool
        result = _tcp_probe("localhost", 65535)  # unlikely open port
        assert isinstance(result, bool)
        # Port 0 is invalid
        assert not _tcp_probe("localhost", 0)

    @patch("cli.server.status")
    def test_status_api(self, mock_status):
        from cli.server import status
        mock_status.return_value = {"running": False, "pid": None}
        result = status()
        assert isinstance(result, dict)

    @patch("cli.server.start")
    def test_ensure_already_running(self, mock_start, mock_settings):
        from cli.server import ensure
        with patch("cli.server.status") as mock_status:
            mock_status.return_value = {"running": True, "pid": 12345}
            result = ensure()
            assert result["running"]
            mock_start.assert_not_called()

    @patch("cli.server.start")
    def test_ensure_starts_if_not_running(self, mock_start, mock_settings):
        from cli.server import ensure
        with patch("cli.server.status") as mock_status:
            mock_status.return_value = {"running": False, "pid": None}
            with patch("cli.server._probe_port") as mock_probe:
                mock_probe.return_value = False
                mock_start.return_value = {"running": True, "pid": 12345}
                result = ensure()
                assert result["running"]
                mock_start.assert_called_once()
                mock_probe.assert_called_once()


# ═════════════════════════════════════════════════════════════════════
# Tests: auth.py
# ═════════════════════════════════════════════════════════════════════


class TestAuth:
    def test_login_guides(self):
        from cli.auth import LOGIN_GUIDES
        assert "gemini" in LOGIN_GUIDES
        assert "openai" in LOGIN_GUIDES
        assert LOGIN_GUIDES["gemini"]["env_var"] == "GEMINI_API_KEY"
        assert "url" in LOGIN_GUIDES["gemini"]

    def test_login_status(self, mock_settings):
        from cli.auth import login_status
        statuses = login_status(mock_settings)
        gemini = [s for s in statuses if s["name"] == "gemini"]
        assert len(gemini) == 1
        assert gemini[0]["has_key"]

        openai = [s for s in statuses if s["name"] == "openai"]
        assert len(openai) == 1
        assert not openai[0]["has_key"]

        anthropic = [s for s in statuses if s["name"] == "anthropic"]
        assert len(anthropic) == 1
        assert anthropic[0]["has_key"]


# ═════════════════════════════════════════════════════════════════════
# Tests: cli/__init__.py (unit tests for internal functions)
# ═════════════════════════════════════════════════════════════════════


class TestCLIInit:
    def test_extract_error_message(self):
        from cli import _extract_error_message
        # Plain string
        assert "test error" in _extract_error_message("litellm.RateLimitError: test error")
        # JSON embedded
        msg = _extract_error_message('{"error": {"message": "Rate limit exceeded"}}')
        assert "Rate limit exceeded" in msg
        # Truncation
        long = "x" * 500
        result = _extract_error_message(long)
        assert len(result) <= 310

    def test_categorize_error(self):
        from cli import _categorize_error
        assert _categorize_error("connection refused")["category"] == "connection"
        assert _categorize_error("401 unauthorized")["category"] == "auth"
        assert _categorize_error("429 too many requests")["category"] == "rate_limit"
        assert _categorize_error("model not found")["category"] == "model"
        assert _categorize_error("unknown weird error")["category"] == "unknown"

    def test_categorize_error_auto_health(self):
        from cli import _categorize_error
        assert _categorize_error("invalid API key")["auto_health"] is True
        assert _categorize_error("connection refused")["auto_health"] is False

    def test_fuzzy_command_suggestion(self):
        from cli import _fuzzy_command_suggestion
        assert _fuzzy_command_suggestion("/hel") == "/help"
        assert _fuzzy_command_suggestion("/sttus") == "/status"
        assert _fuzzy_command_suggestion("/exot") == "/exit"
        # Unknown prefix that doesn't match anything — might still get a guess
        suggestion = _fuzzy_command_suggestion("/zzznotacommand")
        assert suggestion is None or suggestion.startswith("/")

    def test_crash_state_operations(self):
        from cli import _save_crash_state, _clear_crash_state, _check_crash_recovery, _CRASH_FILE

        with tempfile.TemporaryDirectory() as tmp:
            with patch("cli._CRASH_FILE", os.path.join(tmp, "crash.json")):
                # No crash state initially
                from rich.console import Console
                con = Console()
                assert _check_crash_recovery(con) is None

                # Save and check
                _save_crash_state("test-sess-123", "gemini", "gpt-4o", "last message")
                sid = _check_crash_recovery(con)
                assert sid == "test-sess-123"

                # Clear and verify
                _clear_crash_state()
                assert _check_crash_recovery(con) is None

    def test_snapshot_operations(self):
        from cli import _save_snapshot, _load_snapshot, _SNAPSHOT_FILE

        with tempfile.TemporaryDirectory() as tmp:
            with patch("cli._SNAPSHOT_FILE", os.path.join(tmp, "snapshot.json")):
                assert _load_snapshot() is None
                _save_snapshot("sess-1", "openai", "gpt-4")
                snap = _load_snapshot()
                assert snap is not None
                assert snap["session_id"] == "sess-1"
                assert snap["provider"] == "openai"


# ═════════════════════════════════════════════════════════════════════
# Tests: New features (run, auth, apply_cli_settings)
# ═════════════════════════════════════════════════════════════════════


class TestNewFeatures:
    def test_detect_providers_from_env(self):
        from cli import _detect_providers_from_env
        result = _detect_providers_from_env()
        assert isinstance(result, list)
        # Check that known env vars are found
        import os
        if "OPENAI_API_KEY" in os.environ:
            assert "openai" in result

    def test_apply_cli_settings_provider(self):
        """_apply_cli_settings should call settings.set for --provider."""
        from cli import _apply_cli_settings
        settings = MagicMock()
        llm = MagicMock()
        memory = MagicMock()
        args = MagicMock()
        args.provider = "openai"
        args.model = None
        args.resume = None

        _apply_cli_settings(settings, llm, memory, args)
        settings.set.assert_called_once_with("provider.active", "openai")
        llm.reload_settings.assert_called_once()

    def test_apply_cli_settings_model(self):
        """_apply_cli_settings should set model for the active provider."""
        from cli import _apply_cli_settings
        settings = MagicMock()
        settings.get.return_value = "gemini"  # active provider
        llm = MagicMock()
        memory = MagicMock()
        args = MagicMock()
        args.provider = None
        args.model = "gemini-2.5-pro"
        args.resume = None

        _apply_cli_settings(settings, llm, memory, args)
        settings.set.assert_called_once_with("provider.gemini.model", "gemini-2.5-pro")
        llm.reload_settings.assert_called_once()

    def test_apply_cli_settings_resume(self):
        """_apply_cli_settings should call set_current_session for --resume."""
        from cli import _apply_cli_settings
        settings = MagicMock()
        llm = MagicMock()
        memory = MagicMock()
        args = MagicMock()
        args.provider = None
        args.model = None
        args.resume = "test-sess-456"

        _apply_cli_settings(settings, llm, memory, args)
        memory.set_current_session.assert_called_once_with("test-sess-456")
        llm.reload_settings.assert_not_called()  # no provider/model change

    def test_handle_run_no_message(self):
        """_handle_run should exit with code 1 when no message given."""
        from cli import _handle_run
        args = MagicMock()
        args.provider = None
        args.model = None
        args.resume = None
        args.json = False
        args.ndjson = False

        # Simulate sys.argv without a message
        import sys
        orig_argv = sys.argv
        sys.argv = ["main.py", "run"]
        try:
            with pytest.raises(SystemExit) as exc:
                _handle_run(args)
            assert exc.value.code == 1
        finally:
            sys.argv = orig_argv

    def test_handle_auth_standalone(self):
        """_handle_auth should not crash when called."""
        from cli import _handle_auth
        from cli.output import set_output_format
        set_output_format("json")
        args = MagicMock()
        args.json = True
        # Should complete without error (reads settings from disk)
        try:
            _handle_auth(args)
        except SystemExit:
            pass  # allowed

    def test_cli_help_shows_new_commands(self):
        """The /help command list should include /crash."""
        from cli import _COMMANDS
        assert "/crash" in _COMMANDS
        # Run and auth are top-level subcommands, not /-commands
