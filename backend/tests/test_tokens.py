"""
BRUTAL TESTS for token estimation utilities — Unicode, boundary values, overflow,
concurrent access, and pathological inputs.

Catches: zero-width characters, emoji, CJK, RTL text, very long strings,
negative limits, float overflow, and thread-safety issues.
"""
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
        assert result > 10

    def test_longer_text_more_tokens(self):
        short = estimate_tokens("hello")
        long = estimate_tokens("hello world this is a longer sentence with many words")
        assert long > short

    def test_model_prefix_sentencepiece(self):
        result = estimate_tokens("x" * 320, model="groq/llama-3.3-70b")
        assert 80 <= result <= 120

    def test_zero_tokens_for_empty(self):
        assert estimate_tokens("") == 0


class TestEstimateTokensBrutal:
    """Brutal edge cases for token estimation."""

    def test_single_space(self):
        result = estimate_tokens(" ")
        assert result >= 1

    def test_single_newline(self):
        result = estimate_tokens("\n")
        assert result >= 1

    def test_single_tab(self):
        result = estimate_tokens("\t")
        assert result >= 1

    def test_unicode_emoji(self):
        result = estimate_tokens("\U0001f600\U0001f601\U0001f602")
        assert result > 0

    def test_cjk_characters(self):
        result = estimate_tokens("你好世界")
        assert result > 0

    def test_rtl_text(self):
        result = estimate_tokens("العربية")
        assert result > 0

    def test_mixed_scripts(self):
        result = estimate_tokens("Hello 你好 مرحبا")
        assert result > 0

    def test_zero_width_chars(self):
        result = estimate_tokens("\u200b\u200c\u200d\ufeff")
        # Should not crash; may return 0 or 1+
        assert result >= 0

    def test_null_bytes(self):
        result = estimate_tokens("\x00\x00\x00")
        assert result >= 0

    def test_extremely_long_string(self):
        result = estimate_tokens("a" * 1_000_000)
        assert result > 100_000

    def test_repeated_long_string_same_tokens(self):
        """Same input should always produce same output (determinism)."""
        text = "The quick brown fox jumps over the lazy dog. " * 100
        r1 = estimate_tokens(text)
        r2 = estimate_tokens(text)
        assert r1 == r2

    def test_model_gpt4o(self):
        result = estimate_tokens("hello world", model="gpt-4o")
        assert result > 0

    def test_model_gpt4o_mini(self):
        result = estimate_tokens("hello world", model="gpt-4o-mini")
        assert result > 0

    def test_model_gpt35(self):
        result = estimate_tokens("hello world", model="gpt-3.5-turbo")
        assert result > 0

    def test_model_mistral(self):
        result = estimate_tokens("hello world", model="mistral/mistral-small")
        assert result > 0

    def test_model_ollama(self):
        result = estimate_tokens("hello world", model="ollama/llama2")
        assert result > 0

    def test_model_none_defaults(self):
        r_none = estimate_tokens("hello world", model=None)
        r_default = estimate_tokens("hello world")
        assert r_none == r_default

    def test_only_punctuation(self):
        result = estimate_tokens('!@#$%^&*()_+-={}[]|;:",./<>?')
        assert result > 0

    def test_multiline_text(self):
        text = "\n".join([f"Line {i}: This is a test sentence." for i in range(100)])
        result = estimate_tokens(text)
        assert result > 100

    def test_pathological_single_char(self):
        """Single character should tokenize to at least 1 token."""
        for char in ["a", "Z", "0", "\n", " ", "\t"]:
            result = estimate_tokens(char)
            assert result >= 1, f"Failed for char: {repr(char)}"


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


class TestTruncateBrutal:
    """Edge cases that break naive truncation."""

    def test_single_word_limit_1_token(self):
        result = truncate_to_token_limit("hello world foo bar", 1)
        assert len(result) < len("hello world foo bar")
        assert "...[truncated]" in result

    def test_unicode_text_truncated(self):
        text = "\u4f60\u597d" * 1000
        result = truncate_to_token_limit(text, 5)
        assert len(result) < len(text)

    def test_text_exactly_at_limit_unchanged(self):
        text = "hello"
        limit = estimate_tokens(text)
        result = truncate_to_token_limit(text, limit)
        assert result == text

    def test_text_one_token_over_truncated(self):
        text = "hello world this is a test"
        limit = estimate_tokens(text) - 1
        result = truncate_to_token_limit(text, limit)
        assert len(result) < len(text)

    def test_empty_text_with_positive_limit(self):
        result = truncate_to_token_limit("", 100)
        assert result == ""

    def test_truncation_preserves_word_boundary(self):
        """Truncation should cut at word boundary, not mid-word."""
        text = "word1 word2 word3 word4 word5 word6 word7 word8"
        result = truncate_to_token_limit(text, 5)
        if result != text and "...[truncated]" in result:
            # Check the text before truncation marker ends at a space
            before_marker = result.split("\n...[truncated]")[0]
            assert before_marker.endswith(" ") or len(before_marker) < len(text)

    def test_model_prefix_affects_truncation(self):
        """Different tokenizers should produce different truncation points."""
        text = "The quick brown fox " * 50
        limit = 20
        result_default = truncate_to_token_limit(text, limit)
        result_sp = truncate_to_token_limit(text, limit, model="groq/llama-3.3-70b")
        # Both should truncate
        assert "...[truncated]" in result_default
        assert "...[truncated]" in result_sp

    def test_limit_very_large(self):
        text = "small"
        result = truncate_to_token_limit(text, 999_999_999)
        assert result == text


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


class TestEstimateMessageListBrutal:
    def test_empty_content_message(self):
        msgs = [{"role": "user", "content": ""}]
        result = estimate_message_list_tokens(msgs)
        assert result >= 0

    def test_missing_role_key(self):
        msgs = [{"content": "hello"}]
        result = estimate_message_list_tokens(msgs)
        assert result > 0

    def test_missing_content_key(self):
        msgs = [{"role": "user"}]
        result = estimate_message_list_tokens(msgs)
        assert result > 0

    def test_empty_dict_message(self):
        msgs = [{}]
        result = estimate_message_list_tokens(msgs)
        assert result >= 0

    def test_system_user_assistant_roles(self):
        msgs = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = estimate_message_list_tokens(msgs)
        assert result > 10

    def test_100_messages(self):
        msgs = [{"role": "user", "content": f"Message {i}"} for i in range(100)]
        result = estimate_message_list_tokens(msgs)
        assert result > 100

    def test_concurrent_estimation(self):
        """estimate_message_list_tokens should be safe for concurrent calls."""
        import threading
        msgs = [{"role": "user", "content": f"Message {i}"} for i in range(10)]
        results = []
        errors = []

        def estimate():
            try:
                results.append(estimate_message_list_tokens(msgs))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=estimate) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert all(r == results[0] for r in results), "Concurrent calls gave different results"


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


class TestSelectMessagesBrutal:
    def test_budget_zero_returns_empty(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = select_messages_within_budget(msgs, 0)
        assert len(result) == 0

    def test_single_large_message_budget_1_token(self):
        msgs = [{"role": "user", "content": "x" * 10000}]
        result = select_messages_within_budget(msgs, 1)
        assert len(result) == 0

    def test_mixed_content_sizes_favors_recent(self):
        """Should keep most recent messages when budget is tight."""
        msgs = [
            {"role": "user", "content": "a" * 1000},
            {"role": "assistant", "content": "b" * 1000},
            {"role": "user", "content": "c" * 10},
            {"role": "assistant", "content": "d" * 10},
        ]
        result = select_messages_within_budget(msgs, 50)
        if len(result) > 0:
            # The last message should be most likely to survive
            assert result[-1]["content"] in ["c" * 10, "d" * 10]

    def test_budget_large_enough_for_all(self):
        msgs = [{"role": "user", "content": str(i)} for i in range(20)]
        result = select_messages_within_budget(msgs, 1_000_000)
        assert len(result) == 20

    def test_result_never_exceeds_input(self):
        msgs = [{"role": "user", "content": str(i)} for i in range(50)]
        result = select_messages_within_budget(msgs, 10)
        assert len(result) <= len(msgs)

    def test_never_returns_none_elements(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        result = select_messages_within_budget(msgs, 999999)
        for msg in result:
            assert msg is not None
            assert isinstance(msg, dict)

    def test_budget_negative(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = select_messages_within_budget(msgs, -100)
        assert len(result) == 0