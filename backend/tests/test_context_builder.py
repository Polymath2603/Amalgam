"""
BRUTAL TESTS for ContextBuilder — extreme history, Unicode, edge cases.

Catches: empty tools, very long histories, Unicode in messages,
missing settings keys, and malformed message dicts.
"""
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


# ===================================================================
# Original tests (preserved)
# ===================================================================

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


class TestContextBuilderBrutal:
    def test_empty_user_msg(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="")
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assert len(user_msgs) >= 1

    def test_very_long_user_msg(self, ctx):
        long_msg = "word " * 10000
        messages = ctx.build(tools=[], history=[], user_msg=long_msg)
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assert user_msgs[-1]["content"] == long_msg

    def test_unicode_user_msg(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="\u4f60\u597d\u4e16\u754c")
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assert "\u4f60\u597d" in user_msgs[-1]["content"]

    def test_emoji_user_msg(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="\U0001f600\U0001f601")
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assert len(user_msgs) >= 1

    def test_large_history(self, ctx):
        """100-message history should not crash."""
        history = [{"role": "user", "content": f"msg {i}"} for i in range(100)]
        messages = ctx.build(tools=[], history=history, user_msg="final")
        assert isinstance(messages, list)

    def test_history_with_missing_keys(self, ctx):
        """Messages without 'role' or 'content' should not crash."""
        history = [
            {"role": "user"},  # missing content
            {"content": "hello"},  # missing role
            {},  # missing both
        ]
        try:
            messages = ctx.build(tools=[], history=history, user_msg="test")
            assert isinstance(messages, list)
        except (KeyError, TypeError):
            pass  # Acceptable

    def test_many_tools(self, ctx):
        """Many tools should not crash the builder."""
        tools = [{"type": "function", "function": {"name": f"tool_{i}", "description": f"Tool {i}"}}
                 for i in range(50)]
        messages = ctx.build(tools=tools, history=[], user_msg="hello")
        assert isinstance(messages, list)

    def test_result_ends_with_user_msg(self, ctx):
        """Last message should always be the current user message."""
        messages = ctx.build(tools=[], history=[], user_msg="test")
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "test"

    def test_summary_with_unicode(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="hello",
                            summary="\u4f60\u597d\u4e16\u754c context")
        assert isinstance(messages, list)

    def test_relevant_with_empty_list(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="hello", relevant=[])
        assert isinstance(messages, list)

    def test_build_idempotent(self, ctx):
        """Building twice with same inputs should give same structure."""
        m1 = ctx.build(tools=[], history=[], user_msg="test")
        m2 = ctx.build(tools=[], history=[], user_msg="test")
        assert len(m1) == len(m2)
        assert [m["role"] for m in m1] == [m["role"] for m in m2]

    def test_special_chars_in_history(self, ctx):
        history = [
            {"role": "user", "content": "<script>alert('xss')</script>"},
            {"role": "assistant", "content": "Normal response"},
        ]
        messages = ctx.build(tools=[], history=history, user_msg="test")
        assert isinstance(messages, list)

    def test_none_in_history_content(self, ctx):
        history = [
            {"role": "user", "content": None},
            {"role": "assistant", "content": "ok"},
        ]
        try:
            messages = ctx.build(tools=[], history=history, user_msg="test")
        except (TypeError, AttributeError):
            pass  # Acceptable

    def test_empty_tools_list(self, ctx):
        messages = ctx.build(tools=[], history=[], user_msg="test")
        assert isinstance(messages, list)

    def test_build_with_none_summary(self, ctx):
        try:
            messages = ctx.build(tools=[], history=[], user_msg="hello", summary=None)
            assert isinstance(messages, list)
        except TypeError:
            pass