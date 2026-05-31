"""Tests for token estimation utilities — pure functions, no mocks."""
from backend.core.utils.tokens import (
    estimate_tokens,
    truncate_to_token_limit,
    estimate_message_list_tokens,
    select_messages_within_budget,
)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_text(self):
        result = estimate_tokens("hello world")
        assert result > 0

    def test_400_chars_multiple_tokens(self):
        result = estimate_tokens("x" * 400)
        assert result > 10  # should tokenize into multiple tokens

    def test_longer_text_more_tokens(self):
        short = estimate_tokens("hello")
        long = estimate_tokens("hello world this is a longer sentence with many words")
        assert long > short

    def test_model_prefix_sentencepiece(self):
        result = estimate_tokens("x" * 320, model="groq/llama-3.3-70b")
        assert 80 <= result <= 120

    def test_zero_tokens_for_none(self):
        assert estimate_tokens("") == 0


class TestTruncateToTokenLimit:
    def test_short_text_unchanged(self):
        text = "hello world"
        assert truncate_to_token_limit(text, 999999) == text

    def test_long_text_truncated(self):
        text = "word " * 1000
        result = truncate_to_token_limit(text, 10)
        assert len(result) < len(text)
        assert "...[truncated]" in result

    def test_zero_limit_returns_empty(self):
        assert truncate_to_token_limit("hello", 0) == ""

    def test_negative_limit_returns_empty(self):
        assert truncate_to_token_limit("hello", -5) == ""


class TestEstimateMessageListTokens:
    def test_single_message(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = estimate_message_list_tokens(msgs)
        assert result > 0

    def test_multiple_messages_more_tokens(self):
        one = [{"role": "user", "content": "hi"}]
        three = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "how are you"},
        ]
        assert estimate_message_list_tokens(three) > estimate_message_list_tokens(one)

    def test_empty_messages(self):
        result = estimate_message_list_tokens([])
        assert result >= 0


class TestSelectMessagesWithinBudget:
    def test_all_fit_in_budget(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = select_messages_within_budget(msgs, 999999)
        assert len(result) == 2

    def test_tight_budget_truncates(self):
        msgs = [
            {"role": "user", "content": "a" * 500},
            {"role": "assistant", "content": "b" * 500},
            {"role": "user", "content": "c" * 500},
        ]
        result = select_messages_within_budget(msgs, 50)
        assert len(result) < len(msgs)

    def test_empty_messages(self):
        result = select_messages_within_budget([], 100)
        assert result == []

    def test_preserves_chronological_order(self):
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ]
        result = select_messages_within_budget(msgs, 999999)
        assert result[0]["content"] == "first"
        assert result[-1]["content"] == "third"
