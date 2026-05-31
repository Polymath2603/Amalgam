"""Tests for Memory — filesystem tests with tmp_path."""
import pytest
import asyncio
import time
from unittest.mock import MagicMock
from pathlib import Path
from backend.core.memory import Memory


@pytest.fixture
def memory(tmp_path):
    """Create a Memory instance with temporary directories."""
    conv_dir = str(tmp_path / "conversations")

    import os
    os.makedirs(conv_dir, exist_ok=True)

    mock_settings = MagicMock()
    mock_settings.get.side_effect = lambda key, default=None: {
        "memory.summarize_threshold": 40,
        "memory.summarize_keep": 15,
    }.get(key, default)

    m = Memory(llm_router=None, db_path=conv_dir, settings=mock_settings)
    return m


class TestSessionLifecycle:
    def test_start_session_returns_id(self, memory):
        sid = memory.start_session()
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_get_current_session(self, memory):
        sid = memory.start_session()
        assert memory.get_current_session() == sid

    def test_set_current_session(self, memory):
        sid1 = memory.start_session()
        time.sleep(1.1)
        sid2 = memory.start_session()
        memory.set_current_session(sid1)
        assert memory.get_current_session() == sid1

    def test_session_exists(self, memory):
        sid = memory.start_session()
        assert memory.session_exists(sid) is True

    def test_session_not_exists(self, memory):
        assert memory.session_exists("nonexistent-id") is False

    def test_get_sessions_empty(self, memory):
        sessions = memory.get_sessions()
        assert isinstance(sessions, list)

    def test_get_sessions_after_creation(self, memory):
        memory.start_session()
        time.sleep(1.1)
        memory.start_session()
        sessions = memory.get_sessions()
        assert len(sessions) >= 2


def _run(coro):
    """Helper to run async code in sync tests."""
    return asyncio.run(coro)


class TestAddTurnAndGetRecent:
    def test_add_turn_user(self, memory):
        memory.start_session()
        _run(memory.add_turn("user", "hello world"))
        recent = memory.get_recent()
        assert len(recent) >= 1
        assert recent[-1]["role"] == "user"
        assert recent[-1]["content"] == "hello world"

    def test_add_turn_assistant(self, memory):
        memory.start_session()
        _run(memory.add_turn("user", "hi"))
        _run(memory.add_turn("assistant", "hello!"))
        recent = memory.get_recent()
        assert len(recent) >= 2
        assert recent[-1]["role"] == "assistant"

    def test_get_recent_limit(self, memory):
        memory.start_session()
        for i in range(5):
            _run(memory.add_turn("user", f"message {i}"))
        recent = memory.get_recent(3)
        assert len(recent) == 3

    def test_get_recent_all(self, memory):
        memory.start_session()
        for i in range(3):
            _run(memory.add_turn("user", f"msg {i}"))
        recent = memory.get_recent()
        assert len(recent) >= 3


class TestMultipleSessions:
    def test_sessions_isolated(self, memory):
        sid1 = memory.start_session()
        _run(memory.add_turn("user", "session 1 message"))
        time.sleep(1.1)

        sid2 = memory.start_session()
        _run(memory.add_turn("user", "session 2 message"))

        memory.set_current_session(sid1)
        recent1 = memory.get_recent()
        assert any("session 1" in m["content"] for m in recent1)

        memory.set_current_session(sid2)
        recent2 = memory.get_recent()
        assert any("session 2" in m["content"] for m in recent2)


class TestGetSummary:
    def test_empty_summary(self, memory):
        memory.start_session()
        summary = memory.get_summary()
        assert summary == ""

    def test_get_session_messages(self, memory):
        sid = memory.start_session()
        _run(memory.add_turn("user", "test message"))
        messages = memory.get_session_messages(sid)
        assert len(messages) >= 1
        assert messages[0]["role"] == "user"
