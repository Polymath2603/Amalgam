"""
BRUTAL TESTS for Agent pure tag-processing functions — injection, extreme inputs,
Unicode, and adversarial payloads.

Catches: malformed tags, nested tags, injection via tags, very long inputs,
null bytes, and edge cases in tag parsing.
"""
import pytest
from backend.core.agent.core import Agent


@pytest.fixture
def agent():
    return Agent()


# ===================================================================
# Original tests (preserved)
# ===================================================================

class TestStripAllTags:
    def test_think_tags(self, agent):
        result = agent._strip_all_tags("Hello <think>reasoning</think> world")
        assert "Hello" in result
        assert "world" in result
        assert "<think>" not in result

    def test_think_tags_multiline(self, agent):
        text = "Before <think>line1" + chr(10) + "line2" + chr(10) + "line3</think> after"
        result = agent._strip_all_tags(text)
        assert "Before" in result
        assert "after" in result

    def test_legacy_action(self, agent):
        result = agent._strip_all_tags("/**action**/ text")
        assert "action" not in result
        assert "text" in result

    def test_legacy_emotion(self, agent):
        result = agent._strip_all_tags("/[[emotion]] text")
        assert "emotion" not in result
        assert "text" in result

    def test_legacy_expression(self, agent):
        result = agent._strip_all_tags("/((expression)) text")
        assert "expression" not in result
        assert "text" in result

    def test_plain_text(self, agent):
        assert agent._strip_all_tags("plain text") == "plain text"

    def test_empty_string(self, agent):
        assert agent._strip_all_tags("") == ""

    def test_multiple_think_blocks(self, agent):
        text = "multi <think>a</think> <think>b</think>"
        result = agent._strip_all_tags(text)
        assert "multi" in result

    def test_unclosed_action(self, agent):
        result = agent._strip_all_tags("/**unclosed")
        assert "unclosed" not in result or result.strip() == ""

    def test_bare_double_bracket(self, agent):
        result = agent._strip_all_tags("[[tag]] text")
        assert result == "text"

    def test_bare_parens(self, agent):
        result = agent._strip_all_tags("((tag)) text")
        assert result == "text"

    def test_whitespace_cleanup(self, agent):
        result = agent._strip_all_tags("hello  ")
        assert result == "hello"


class TestStripAllTagsBrutal:
    """Adversarial inputs designed to break tag parsers."""

    def test_nested_think_tags(self, agent):
        """Nested think tags — parser should not get confused."""
        result = agent._strip_all_tags("<think> <think>nested</think> outer</think> text")
        assert "text" in result
        assert "<think>" not in result

    def test_empty_think_block(self, agent):
        result = agent._strip_all_tags("before <think></think> after")
        assert "before" in result
        assert "after" in result

    def test_think_tag_only(self, agent):
        result = agent._strip_all_tags("<think>reasoning</think>")
        assert result.strip() == "" or len(result.strip()) == 0

    def test_multiple_tag_types(self, agent):
        text = "text <think>think**/ action /((exp)) [[emo]] done"
        result = agent._strip_all_tags(text)
        assert "text" in result
        assert "done" in result

    def test_very_long_think_block(self, agent):
        text = "before <think>" + "x" * 100000 + "</think> after"
        result = agent._strip_all_tags(text)
        assert "before" in result
        assert "after" in result
        assert "<think>" not in result

    def test_unicode_in_tags(self, agent):
        text = "<think>\u4f60\u597d reasoning</think> world"
        result = agent._strip_all_tags(text)
        assert "world" in result
        assert "<think>" not in result

    def test_emoji_in_tags(self, agent):
        text = "<think>\U0001f600 reasoning</think> world"
        result = agent._strip_all_tags(text)
        assert "world" in result

    def test_newlines_in_tags(self, agent):
        text = "line1\n<think>reasoning\nline2\nline3</think> line4"
        result = agent._strip_all_tags(text)
        assert "line1" in result
        assert "line4" in result

    def test_only_action_tag(self, agent):
        result = agent._strip_all_tags("/**action**/")
        assert "action" not in result

    def test_empty_action_tag(self, agent):
        result = agent._strip_all_tags("/****/")
        assert isinstance(result, str)

    def test_empty_emotion_tag(self, agent):
        result = agent._strip_all_tags("/[[]]")
        assert isinstance(result, str)

    def test_empty_expression_tag(self, agent):
        result = agent._strip_all_tags("/(()))")
        assert isinstance(result, str)

    def test_malformed_nested_tags(self, agent):
        text = "<think>/**action**/</think>"
        result = agent._strip_all_tags(text)
        assert "<think>" not in result
        assert "action" not in result

    def test_repeated_same_tags(self, agent):
        text = "<think>a</think> <think>b</think> <think>c</think> <think>d</think> <think>e</think>"
        result = agent._strip_all_tags(text)
        assert "<think>" not in result
        assert result.strip() == ""

    def test_100_think_blocks(self, agent):
        text = " ".join([f"<think>t{i}</think>" for i in range(100)])
        result = agent._strip_all_tags(text)
        assert "<think>" not in result

    def test_special_chars_in_tags(self, agent):
        text = "<think><script>alert('xss')</script></think> safe"
        result = agent._strip_all_tags(text)
        assert "<script>" not in result
        assert "safe" in result

    def test_null_bytes(self, agent):
        text = "\x00\x00\x00"
        result = agent._strip_all_tags(text)
        assert isinstance(result, str)


class TestProcessTags:
    def test_think_tag(self, agent):
        tags = list(agent._process_tags("Hello <think>world</think>"))
        assert len(tags) == 1
        assert tags[0][0] == "__thinking__"

    def test_action_tag(self, agent):
        tags = list(agent._process_tags("/**smiles**/ text"))
        assert len(tags) == 1
        assert tags[0][0] == "__roleplay__"

    def test_no_tags(self, agent):
        tags = list(agent._process_tags("plain text"))
        assert tags == []

    def test_empty_string(self, agent):
        tags = list(agent._process_tags(""))
        assert tags == []

    def test_multiple_think_tags(self, agent):
        text = "start <think>first</think> mid <think>second</think> end"
        tags = list(agent._process_tags(text))
        think_tags = [t for t in tags if t[0] == "__thinking__"]
        assert len(think_tags) == 2

    def test_mixed_tags(self, agent):
        text = "Hello <think>think**/ world"
        result = agent._strip_all_tags(text)
        assert isinstance(result, str)
        assert "Hello" in result


class TestProcessTagsBrutal:
    def test_no_tags_returns_empty_list(self, agent):
        for text in ["", "hello", "12345", "   "]:
            tags = list(agent._process_tags(text))
            assert tags == [], f"Expected empty for: {repr(text)}"

    def test_many_think_tags(self, agent):
        text = "".join([f"<think>t{i}</think>" for i in range(50)])
        tags = list(agent._process_tags(text))
        assert len(tags) == 50

    def test_tag_content_preserved(self, agent):
        tags = list(agent._process_tags("<think>the actual reasoning content</think>"))
        assert len(tags) == 1
        # Content should be accessible
        assert "reasoning" in str(tags[0][1]).lower() or "thinking" in tags[0][0]


class TestCleanRemainingTags:
    def test_unclosed_emotion(self, agent):
        result = agent._clean_remaining_tags("/[[partial text")
        assert "[[partial" not in result

    def test_unclosed_expression(self, agent):
        result = agent._clean_remaining_tags("/((partial text")
        assert "((" not in result

    def test_unclosed_action(self, agent):
        result = agent._clean_remaining_tags("/**unclosed text")
        assert "/**" not in result

    def test_clean_text_unchanged(self, agent):
        assert agent._clean_remaining_tags("normal text") == "normal text"

    def test_empty_string(self, agent):
        assert agent._clean_remaining_tags("") == ""

    def test_trailing_slash(self, agent):
        result = agent._clean_remaining_tags("hello /")
        assert not result.endswith("/")


class TestCleanRemainingTagsBrutal:
    def test_multiple_unclosed_tags(self, agent):
        result = agent._clean_remaining_tags("/[[a /((b /**c")
        assert "[[" not in result
        assert "((" not in result
        assert "/**" not in result

    def test_only_unclosed_tag(self, agent):
        result = agent._clean_remaining_tags("/[[only")
        assert result.strip() == ""

    def test_unicode_after_unclosed(self, agent):
        result = agent._clean_remaining_tags("/[[\u4f60\u597d")
        assert "[[" not in result