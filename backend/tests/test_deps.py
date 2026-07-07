"""Tests for deps.py — singleton behavior and thread safety."""
import pytest
import threading
from backend.core.deps import get_shared, _shared, _init_lock, set_agent_type, get_active_agent_type
from backend.core.agent.basic_agent import BasicAgent
from backend.core.agent.reflective_agent import ReflectiveAgent


class TestGetShared:
    def test_returns_dict(self):
        result = get_shared()
        assert isinstance(result, dict)

    def test_has_all_keys(self):
        result = get_shared()
        for key in ["settings", "llm", "memory", "context_builder",
                     "context_manager", "vault", "mcp", "tts",
                     "agent", "relationship", "wakeword"]:
            assert key in result

    def test_settings_not_none(self):
        result = get_shared()
        assert result["settings"] is not None

    def test_singleton_returns_same_dict(self):
        r1 = get_shared()
        r2 = get_shared()
        assert r1 is r2

    def test_thread_safety(self):
        results = []
        errors = []

        def call_get_shared():
            try:
                r = get_shared()
                results.append(id(r))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=call_get_shared) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(set(results)) == 1


class TestSetAgentType:
    """
    Backs the /direct command (TUI and WebUI): verifies the live agent
    instance in shared state actually swaps class, not just a settings
    flag that nothing reads. This replaced an earlier, non-functional
    `orchestrator.enabled` toggle found during audit — that key was never
    read anywhere in the codebase, so flipping it did nothing.
    """

    def setup_method(self):
        get_shared()  # ensure startup has run at least once
        self._original_type = get_active_agent_type()

    def teardown_method(self):
        # Restore whatever was active before this test ran, so other tests
        # in the suite that depend on the default agent type aren't affected.
        set_agent_type(self._original_type)

    def test_set_agent_type_basic_produces_a_basic_agent(self):
        agent = set_agent_type("basic")
        assert isinstance(agent, BasicAgent)
        assert not isinstance(agent, ReflectiveAgent)

    def test_set_agent_type_updates_shared_state(self):
        set_agent_type("basic")
        assert isinstance(get_shared()["agent"], BasicAgent)

    def test_set_agent_type_updates_get_active_agent_type(self):
        set_agent_type("basic")
        assert get_active_agent_type() == "basic"

    def test_set_agent_type_none_restores_configured_default(self):
        set_agent_type("basic")
        assert get_active_agent_type() == "basic"

        set_agent_type(None)
        restored_type = get_active_agent_type()
        # Restores to whatever `agent.type` is configured as (default:
        # reflective_planning) — not hardcoded to "basic" again.
        assert restored_type != "basic" or get_shared()["settings"].get("agent.type") == "basic"

    def test_direct_mode_round_trip_matches_the_actual_slash_command_logic(self):
        """Mirrors exactly what _handle_direct_command does: toggle to
        basic, then toggle back, and confirm the agent class actually
        changes both times — not just the string label."""
        set_agent_type(None)  # ensure known starting state
        starting_type = get_active_agent_type()
        assert starting_type != "basic", "test assumes a non-basic default; adjust if config changes"

        set_agent_type("basic")
        assert get_active_agent_type() == "basic"
        assert isinstance(get_shared()["agent"], BasicAgent)

        set_agent_type(None)
        assert get_active_agent_type() == starting_type
        assert not isinstance(get_shared()["agent"], BasicAgent)
