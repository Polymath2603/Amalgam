"""Tests for deps.py — singleton behavior and thread safety."""
import pytest
import threading
from backend.core.deps import get_shared, _shared, _init_lock


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
