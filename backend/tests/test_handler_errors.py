"""Tests for _normalize_error — pure function, no mocks."""
from backend.api.ws.handler import _normalize_error
import json


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
