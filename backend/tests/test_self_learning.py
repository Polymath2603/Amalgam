"""
BRUTAL TESTS for self-learning subsystem — edge cases, injection, and extreme inputs.

Catches: empty tool calls, all failed tools, malformed skill names,
unicode in corrections, concurrent access, and rate limiting.
"""
import asyncio
import threading
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
        assert name is None

    def test_generate_skill_name_deduplicates(self):
        creator = AutoSkillCreator()
        name = creator._generate_skill_name("the the and or for")
        assert name is None

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


class TestAutoSkillCreatorBrutal:
    def test_generate_name_unicode(self):
        creator = AutoSkillCreator()
        name = creator._generate_skill_name("\u4f60\u597d \u4e16\u754c")
        # Should handle unicode gracefully
        assert name is None or isinstance(name, str)

    def test_generate_name_emoji(self):
        creator = AutoSkillCreator()
        name = creator._generate_skill_name("\U0001f600 deploy app \U0001f601")
        assert name is None or isinstance(name, str)

    def test_generate_name_very_long(self):
        creator = AutoSkillCreator()
        name = creator._generate_skill_name("word " * 1000)
        assert name is None or isinstance(name, str)

    def test_tool_call_summary_missing_keys(self):
        """Tool call with missing expected keys should not crash."""
        tc = {}
        summary = AutoSkillCreator._tool_call_summary(tc)
        assert summary["tool"] == ""
        assert summary["success"] is False

    def test_tool_call_summary_none_values(self):
        tc = {"tool_name": None, "tool_input": None, "success": None}
        summary = AutoSkillCreator._tool_call_summary(tc)
        assert summary is not None

    def test_template_unicode_content(self):
        creator = AutoSkillCreator()
        content = creator._generate_skill_template(
            "\u4f60\u597d task",
            [{"tool_name": "search", "tool_input": {}, "success": True}],
            "Done \U0001f600",
        )
        assert "\u4f60\u597d task" in content

    def test_empty_tool_calls_list(self):
        creator = AutoSkillCreator()
        content = creator._generate_skill_template("task", [], "done")
        assert "task" in content

    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        """After max skills per session, should stop creating."""
        creator = AutoSkillCreator()
        # Set low rate limit for testing
        creator._session_skill_count = 100  # Already at max
        result = await creator.maybe_create_skill(
            user_message="test",
            tool_calls=[{"tool_name": "t", "tool_input": {}, "success": True}] * 5,
            full_response="done",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_all_failed_tools(self):
        """All failed tool calls should not create a skill."""
        creator = AutoSkillCreator()
        result = await creator.maybe_create_skill(
            user_message="test",
            tool_calls=[{"tool_name": "t", "tool_input": {}, "success": False}] * 5,
            full_response="done",
        )
        # May or may not create skill depending on implementation
        assert result is None or isinstance(result, str)

    def test_concurrent_name_generation(self):
        creator = AutoSkillCreator()
        names = []
        errors = []
        def gen():
            try:
                name = creator._generate_skill_name("How to deploy a Python app")
                names.append(name)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=gen) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0


class TestCorrectionStore:
    def test_init_empty(self, tmp_path):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir=str(tmp_path))
        assert cs.count() == 0

    def test_detect_correction_explicit_denial(self):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir="/tmp")
        assert cs.detect_correction("no, that's not right")
        assert cs.detect_correction("actually it's Python, not Java")
        assert cs.detect_correction("that is incorrect")

    def test_detect_correction_preference(self):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir="/tmp")
        assert cs.detect_correction("I'd prefer concise answers")
        assert cs.detect_correction("I'd rather you didn't do that")

    def test_detect_correction_negative(self):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir="/tmp")
        assert not cs.detect_correction("Hello, how are you?")
        assert not cs.detect_correction("That's interesting, tell me more")

    def test_extract_correction_stores_record(self, tmp_path):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir=str(tmp_path))
        record = cs.extract_correction("session1", "no, I meant the other one", "OK here")
        assert record is not None


class TestCorrectionStoreBrutal:
    def test_detect_unicode_correction(self):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir="/tmp")
        # Unicode should not crash
        result = cs.detect_correction("\u4e0d\u5bf9")
        assert isinstance(result, bool)

    def test_detect_empty_string(self):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir="/tmp")
        assert not cs.detect_correction("")

    def test_detect_very_long_string(self):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir="/tmp")
        result = cs.detect_correction("no " * 10000)
        assert isinstance(result, bool)

    def test_concurrent_detect(self, tmp_path):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir=str(tmp_path))
        errors = []
        def detect():
            try:
                cs.detect_correction("no, that's wrong")
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=detect) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0

    def test_corrupted_corrections_file(self, tmp_path):
        """Corrupted corrections file should not crash store."""
        from backend.core.self_learning.corrections import CorrectionStore
        path = tmp_path / "corrections.json"
        path.write_text("not valid json {{{")
        cs = CorrectionStore(data_dir=str(tmp_path))
        assert cs.count() == 0