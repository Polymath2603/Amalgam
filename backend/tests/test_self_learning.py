"""Tests for self-learning subsystem (AutoSkillCreator)."""

import pytest
from pathlib import Path
from backend.core.self_learning.auto_skill import AutoSkillCreator


class TestAutoSkillCreator:
    @pytest.mark.asyncio
    async def test_skip_few_tool_calls(self):
        creator = AutoSkillCreator()
        result = await creator.maybe_create_skill(
            user_message="hello",
            tool_calls=[{"tool_name": "search", "tool_input": {}, "success": True}],
            full_response="OK",
        )
        # Should return None because MIN_TOOL_CALLS_FOR_SKILL=3
        assert result is None

    def test_generate_skill_name_generates_hyphenated(self):
        creator = AutoSkillCreator()
        name = creator._generate_skill_name("How do I deploy a Django app to production?")
        assert name is not None
        assert "-" in name
        assert len(name) > 8

    def test_generate_skill_name_short_text(self):
        creator = AutoSkillCreator()
        name = creator._generate_skill_name("hi")
        # All stopwords or too short → should return None
        assert name is None

    def test_generate_skill_name_deduplicates(self):
        creator = AutoSkillCreator()
        name = creator._generate_skill_name("the the and or for")
        assert name is None  # all stopwords

    def test_tool_call_summary_from_dict(self):
        tc = {"tool_name": "search", "tool_input": {"q": "test"}, "success": True}
        summary = AutoSkillCreator._tool_call_summary(tc)
        assert summary["tool"] == "search"
        assert summary["input"] == {"q": "test"}
        assert summary["success"] is True

    def test_tool_call_summary_from_object(self):
        class FakeToolCall:
            tool_name = "search"
            tool_input = {"q": "test"}
            success = True

        summary = AutoSkillCreator._tool_call_summary(FakeToolCall())
        assert summary["tool"] == "search"

    def test_template_generation(self):
        creator = AutoSkillCreator()
        content = creator._generate_skill_template(
            "deploy django app",
            [
                {"tool_name": "shell", "tool_input": {}, "success": True},
                {"tool_name": "file_write", "tool_input": {}, "success": True},
                {"tool_name": "shell", "tool_input": {}, "success": True},
            ],
            "Done.",
        )
        assert "deploy django app" in content
        assert "## Steps" in content
        assert "## Tools Used" in content
        assert "shell" in content
        assert "file_write" in content

    def test_list_recent_skills_returns_empty_if_no_dir(self, monkeypatch):
        monkeypatch.setattr("backend.core.self_learning.auto_skill.SKILLS_DIR", Path("/nonexistent"))
        creator = AutoSkillCreator()
        result = creator.list_recent_skills()
        assert result == []
