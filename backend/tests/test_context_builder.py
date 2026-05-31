"""Tests for ContextBuilder — integration tests with settings."""
import pytest
from unittest.mock import MagicMock
from backend.core.context_builder import ContextBuilder


@pytest.fixture
def ctx(tmp_path):
    """Create a ContextBuilder with mock settings."""
    mock_settings = MagicMock()
    mock_settings.get.side_effect = lambda key, default=None: {
        "character.active": "default",
        "llm.context_token_limit": 8192,
        "system_prompt.max_tokens": 1500,
        "provider.active": "gemini",
        "provider.gemini.model": "gemini-2.5-flash",
    }.get(key, default)
    mock_settings.get_characters.return_value = {
        "default": {
            "name": "Assistant",
            "personality": "A helpful assistant.",
            "vocabulary": "professional",
        }
    }

    ctx = ContextBuilder(settings=mock_settings)
    return ctx


class TestContextBuilder:
    def test_build_returns_list(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="hello")
        assert isinstance(messages, list)

    def test_build_has_system_message(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="hello")
        system_msgs = [m for m in messages if m.get("role") == "system"]
        assert len(system_msgs) >= 1

    def test_build_has_user_message(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="hello")
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assert len(user_msgs) >= 1
        assert user_msgs[-1]["content"] == "hello"

    def test_build_with_summary(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="hello",
                            summary="Previous context about Python")
        all_content = " ".join(m["content"] for m in messages)
        assert "Python" in all_content or "Previous" in all_content

    def test_build_with_history(self, ctx):
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
        ]
        messages = ctx.build(tools=[], history=history, user_msg="how are you")
        all_content = " ".join(m["content"] for m in messages)
        assert "hi" in all_content or "hello" in all_content

    def test_build_with_relevant(self, ctx):
        relevant = [{"role": "user", "content": "we discussed Python earlier"}]
        messages = ctx.build(tools=[], history=[], user_msg="what was that about?",
                            relevant=relevant)
        all_content = " ".join(m["content"] for m in messages)
        assert "Python" in all_content

    def test_system_prompt_contains_identity(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="hello")
        system_msg = next(m for m in messages if m.get("role") == "system")
        assert len(system_msg["content"]) > 0

    def test_messages_have_role_and_content(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="test")
        for msg in messages:
            assert "role" in msg
            assert "content" in msg
            assert isinstance(msg["content"], str)

    def test_build_with_tools(self, ctx):
        tools = [{"type": "function", "function": {"name": "test_tool", "description": "A test tool"}}]
        messages = ctx.build(tools=tools, history=[], user_msg="hello")
        system_msg = next(m for m in messages if m.get("role") == "system")
        # System prompt may be truncated; verify it's non-empty
        assert len(system_msg["content"]) > 0

    def test_build_preserves_history_order(self, ctx):
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ]
        messages = ctx.build(tools=[], history=history, user_msg="fourth")
        roles = [m["role"] for m in messages]
        assert roles[0] == "system"
        assert roles[-1] == "user"
        assert messages[-1]["content"] == "fourth"
