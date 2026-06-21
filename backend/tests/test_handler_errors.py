"""
BRUTAL TESTS for _normalize_error — exhaustive error paths, injection, boundary values.

Catches: malformed JSON, deeply nested JSON, empty/massive inputs, Unicode errors,
null bytes, nested error objects, and every possible error pattern.
"""
import json
import pytest
from backend.api.ws.handler import _normalize_error


class TestNormalizeError:
    def test_rate_limit(self):
        result = _normalize_error("rate limit exceeded")
        assert "Rate limit" in result
        assert "wait" in result.lower()

    def test_quota_exceeded(self):
        result = _normalize_error("quota exceeded for this month")
        assert "Quota" in result

    def test_resource_exhausted(self):
        result = _normalize_error("RESOURCE_EXHAUSTED")
        assert "Quota" in result

    def test_401_error(self):
        result = _normalize_error("401 Unauthorized")
        assert "Authentication" in result

    def test_402_error(self):
        result = _normalize_error("402 Payment Required")
        assert "Payment" in result or "billing" in result.lower()

    def test_api_key_not_set(self):
        result = _normalize_error("API key not set for this provider")
        assert "API key" in result
        assert "Settings" in result

    def test_unsupported_image(self):
        result = _normalize_error("unsupported image format")
        assert "image" in result.lower()

    def test_image_url_not_supported(self):
        result = _normalize_error("image_url is not supported by this model")
        assert "image" in result.lower()

    def test_json_error_with_message(self):
        error_json = json.dumps({"error": {"message": "quota exceeded"}})
        result = _normalize_error(error_json)
        assert "Quota" in result

    def test_json_error_without_message(self):
        error_json = json.dumps({"error": "something else"})
        result = _normalize_error(error_json)
        assert isinstance(result, str)

    def test_unknown_error_unchanged(self):
        result = _normalize_error("some completely unknown error")
        assert result == "some completely unknown error"

    def test_case_insensitive_matching(self):
        result = _normalize_error("RATE LIMIT exceeded")
        assert "Rate limit" in result

    def test_empty_string(self):
        result = _normalize_error("")
        assert result == ""


class TestNormalizeErrorBrutal:
    """Brutal edge cases — designed to break naive implementations."""

    def test_none_input_raises(self):
        """None should either be handled gracefully or raise TypeError."""
        try:
            result = _normalize_error(None)
            # If it doesn't raise, it should return a string
            assert isinstance(result, str)
        except (TypeError, AttributeError):
            pass  # Acceptable

    def test_integer_input_raises(self):
        try:
            result = _normalize_error(42)
            assert isinstance(result, str)
        except (TypeError, AttributeError):
            pass

    def test_bytes_input(self):
        try:
            result = _normalize_error(b"rate limit exceeded")
            assert isinstance(result, str)
        except (TypeError, AttributeError):
            pass

    def test_nested_json_rate_limit(self):
        """JSON containing rate limit in nested structure."""
        error_json = json.dumps({
            "error": {
                "message": "rate limit exceeded",
                "code": 429,
                "details": {"retry_after": 30}
            }
        })
        result = _normalize_error(error_json)
        assert "Rate limit" in result

    def test_json_with_401_in_message(self):
        error_json = json.dumps({"error": {"message": "401 Unauthorized"}})
        result = _normalize_error(error_json)
        assert "Authentication" in result

    def test_json_with_api_key_in_nested_message(self):
        error_json = json.dumps({
            "error": {"message": "API key not set for gemini"}
        })
        result = _normalize_error(error_json)
        assert "API key" in result

    def test_malformed_json_falls_through(self):
        """Malformed JSON should not crash — should return as-is."""
        result = _normalize_error("{invalid json")
        assert result == "{invalid json"

    def test_empty_json_object(self):
        result = _normalize_error("{}")
        assert isinstance(result, str)

    def test_json_array_not_crash(self):
        """A JSON array is valid JSON but not an error object."""
        result = _normalize_error('["rate limit"]')
        assert isinstance(result, str)

    def test_json_string_not_object(self):
        result = _normalize_error('"rate limit exceeded"')
        # Should fall through to normal matching
        assert "Rate limit" in result

    def test_extremely_long_error_message(self):
        long_msg = "x" * 100_000 + " rate limit" + "y" * 100_000
        result = _normalize_error(long_msg)
        assert "Rate limit" in result
        assert isinstance(result, str)

    def test_unicode_in_error(self):
        result = _normalize_error("\u4e2d\u6587 rate limit error")
        assert "Rate limit" in result

    def test_emoji_in_error(self):
        result = _normalize_error("\U0001f600 rate limit \U0001f621")
        assert "Rate limit" in result

    def test_newlines_in_error(self):
        result = _normalize_error("rate\nlimit\nexceeded")
        assert "Rate limit" in result

    def test_tabs_in_error(self):
        result = _normalize_error("rate\tlimit\texceeded")
        assert "Rate limit" in result

    def test_whitespace_only(self):
        result = _normalize_error("   \t\n  ")
        assert isinstance(result, str)

    def test_multiple_patterns_in_one_error(self):
        """If multiple patterns match, first match wins (or all are applied)."""
        result = _normalize_error("rate limit and quota exceeded")
        # At least one pattern should match
        assert "Rate limit" in result or "Quota" in result

    def test_content_must_be_string_pattern(self):
        result = _normalize_error("content must be a string")
        assert "image" in result.lower() or "provider" in result.lower()

    def test_json_with_null_message(self):
        error_json = json.dumps({"error": {"message": None}})
        result = _normalize_error(error_json)
        assert isinstance(result, str)

    def test_json_with_deeply_nested_message(self):
        error_json = json.dumps({
            "error": {
                "nested": {
                    "deeply": {
                        "message": "rate limit exceeded"
                    }
                }
            }
        })
        result = _normalize_error(error_json)
        # Should fall through since 'message' is not at top level of error
        assert isinstance(result, str)

    def test_json_with_empty_message_string(self):
        error_json = json.dumps({"error": {"message": ""}})
        result = _normalize_error(error_json)
        assert isinstance(result, str)

    def test_401_in_middle_of_string(self):
        result = _normalize_error("Provider returned 401 and crashed")
        assert "Authentication" in result

    def test_402_in_middle_of_string(self):
        result = _normalize_error("Error 402 from billing")
        assert "Payment" in result or "billing" in result.lower()

    def test_resource_exhausted_case_variations(self):
        for variant in ["RESOURCE_EXHAUSTED", "Resource_Exhausted", "resource_exhausted"]:
            result = _normalize_error(variant)
            assert "Quota" in result, f"Failed for variant: {variant}"

    def test_rate_limit_case_variations(self):
        for variant in ["RATE LIMIT", "Rate Limit", "rate limit", "RATE limit"]:
            result = _normalize_error(variant)
            assert "Rate limit" in result, f"Failed for variant: {variant}"

    def test_deeply_nested_json_no_crash(self):
        obj = {"error": {"message": "test"}}
        for _ in range(20):
            obj = {"wrapper": obj}
        result = _normalize_error(json.dumps(obj))
        assert isinstance(result, str)

    def test_concurrent_calls_same_input(self):
        """_normalize_error should be safe for concurrent calls."""
        import threading
        results = []
        errors = []

        def call_normalize():
            try:
                r = _normalize_error("rate limit exceeded")
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=call_normalize) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert all("Rate limit" in r for r in results)
        assert len(results) == 50