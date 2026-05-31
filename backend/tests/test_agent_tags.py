"""Tests for Agent pure tag-processing functions."""
import pytest
from backend.core.agent import Agent


@pytest.fixture
def agent():
    return Agent()


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
