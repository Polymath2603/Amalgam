"""Tests for the UserProfile system."""

import json
import pytest
from pathlib import Path
from backend.core.user_profile import UserProfile


class TestUserProfile:
    def test_uses_data_dir(self, tmp_path):
        profile = UserProfile(data_dir=str(tmp_path))
        assert profile.path == tmp_path / "user_profile.json"

    def test_default_profile_has_all_keys(self):
        profile = UserProfile(data_dir="/tmp")
        for key in ("name", "timezone", "expertise_areas", "communication_style",
                     "recurring_tasks", "preferences", "languages", "interaction_count"):
            assert key in profile._profile

    def test_get_returns_value(self):
        profile = UserProfile(data_dir="/tmp")
        assert profile.get("name") is None
        assert profile.get("communication_style") == "balanced"
        assert profile.get("nonexistent", "default") == "default"

    def test_save_and_load_roundtrip(self, tmp_path):
        profile = UserProfile(data_dir=str(tmp_path))
        profile._profile["name"] = "TestUser"
        profile.save()

        # Fresh instance loads saved data
        profile2 = UserProfile(data_dir=str(tmp_path))
        assert profile2.get("name") == "TestUser"

    def test_handles_corrupted_file(self, tmp_path):
        profile_path = tmp_path / "user_profile.json"
        profile_path.write_text("corrupted json")
        profile = UserProfile(data_dir=str(tmp_path))
        # Should fall back to defaults
        assert profile.get("name") is None
        assert profile.get("communication_style") == "balanced"

    def test_to_context_string_empty(self):
        profile = UserProfile(data_dir="/tmp")
        # No meaningful info → empty string
        result = profile.to_context_string()
        assert result == ""

    def test_to_context_string_with_name(self):
        profile = UserProfile(data_dir="/tmp")
        profile._profile["name"] = "Alex"
        result = profile.to_context_string()
        assert "User: Alex" in result

    def test_to_context_string_with_style(self):
        profile = UserProfile(data_dir="/tmp")
        profile._profile["communication_style"] = "concise"
        result = profile.to_context_string()
        assert "Prefers concise responses" in result

    def test_to_context_string_ignores_balanced_style(self):
        profile = UserProfile(data_dir="/tmp")
        profile._profile["communication_style"] = "balanced"
        result = profile.to_context_string()
        assert "balanced" not in result

    def test_to_context_string_with_expertise(self):
        profile = UserProfile(data_dir="/tmp")
        profile._profile["expertise_areas"] = ["Python", "ML", "Rust"]
        result = profile.to_context_string()
        assert "Expertise: Python, ML, Rust" in result

    def test_allowed_keys_prevents_injection(self):
        profile = UserProfile(data_dir="/tmp")
        # Simulate LLM trying to inject
        updates = {"name": "Bob", "malicious_key": "injected", "preferences": {}}
        for key, value in updates.items():
            if key not in profile.ALLOWED_KEYS:
                continue
            current_val = profile._profile.get(key)
            if isinstance(value, dict) and isinstance(current_val, dict):
                profile._profile[key].update(value)
            elif value and not current_val:
                profile._profile[key] = value

        assert profile.get("name") == "Bob"
        assert "malicious_key" not in profile._profile

    def test_update_from_session_too_few_messages(self):
        profile = UserProfile(data_dir="/tmp")
        import asyncio
        result = asyncio.run(profile.update_from_session(
            [{"role": "user", "content": "hi"}],
            lambda p: "{}",
        ))
        assert result is False

    def test_update_from_session_empty_llm_response(self):
        profile = UserProfile(data_dir="/tmp")
        import asyncio
        result = asyncio.run(profile.update_from_session(
            [{"role": "user", "content": "My name is Alex"},
             {"role": "assistant", "content": "Hi!"},
             {"role": "user", "content": "I like Python"}],
            lambda p: "{}",
        ))
        assert result is False
