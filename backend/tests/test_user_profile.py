"""Tests for the UserProfile system matching plan spec."""

import json
import pytest
from pathlib import Path
from backend.core.user_profile import UserProfile, ALLOWED_KEYS


class TestUserProfile:
    def test_uses_data_dir(self, tmp_path):
        path = tmp_path / "user_profile.json"
        profile = UserProfile(path=path)
        assert profile.path == path

    def test_default_profile_has_all_keys(self, tmp_path):
        profile = UserProfile(path=tmp_path / "p.json")
        for key in ("name", "timezone", "expertise_areas", "communication_style",
                     "recurring_tasks", "preferences", "languages", "interaction_count"):
            assert key in profile._data

    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "p.json"
        profile = UserProfile(path=path)
        profile._data["name"] = "TestUser"
        profile.save()

        profile2 = UserProfile(path=path)
        assert profile2._data["name"] == "TestUser"

    def test_handles_corrupted_file(self, tmp_path):
        path = tmp_path / "p.json"
        path.write_text("corrupted json")
        profile = UserProfile(path=path)
        assert profile._data["name"] is None
        assert profile._data["communication_style"] == "balanced"

    def test_to_context_string_empty(self, tmp_path):
        profile = UserProfile(path=tmp_path / "p.json")
        result = profile.to_context_string()
        assert result == ""

    def test_to_context_string_with_name(self, tmp_path):
        profile = UserProfile(path=tmp_path / "p.json")
        profile._data["name"] = "Alex"
        result = profile.to_context_string()
        assert "User: Alex" in result

    def test_to_context_string_with_style(self, tmp_path):
        profile = UserProfile(path=tmp_path / "p.json")
        profile._data["communication_style"] = "concise"
        result = profile.to_context_string()
        assert "Prefers concise responses" in result

    def test_to_context_string_ignores_balanced_style(self, tmp_path):
        profile = UserProfile(path=tmp_path / "p.json")
        profile._data["communication_style"] = "balanced"
        result = profile.to_context_string()
        assert "balanced" not in result

    def test_to_context_string_with_expertise(self, tmp_path):
        profile = UserProfile(path=tmp_path / "p.json")
        profile._data["expertise_areas"] = ["Python", "ML", "Rust"]
        result = profile.to_context_string()
        assert "Expertise: Python, ML, Rust" in result

    def test_allowed_keys_prevents_injection(self, tmp_path):
        profile = UserProfile(path=tmp_path / "p.json")
        updates = {"name": "Bob", "malicious_key": "injected", "preferences": {}}
        for key, value in updates.items():
            if key not in ALLOWED_KEYS:
                continue
            current_val = profile._data.get(key)
            if isinstance(value, dict) and isinstance(current_val, dict):
                profile._data[key].update(value)
            elif value and not current_val:
                profile._data[key] = value

        assert profile._data["name"] == "Bob"
        assert "malicious_key" not in profile._data

    def test_update_from_session_too_few_messages(self, tmp_path):
        profile = UserProfile(path=tmp_path / "p.json")
        import asyncio
        result = asyncio.run(profile.update_from_session(
            [{"role": "user", "content": "hi"}],
            lambda p: "{}",
        ))
        assert result is False

    def test_update_from_session_empty_llm_response(self, tmp_path):
        profile = UserProfile(path=tmp_path / "p.json")
        import asyncio
        result = asyncio.run(profile.update_from_session(
            [{"role": "user", "content": "My name is Alex"},
             {"role": "user", "content": "Also I like Python"},
             {"role": "assistant", "content": "Hi!"},
             {"role": "user", "content": "I like Python"}],
            lambda p: "{}",
        ))
        assert result is False
