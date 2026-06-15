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
        assert record["session_id"] == "session1"
        assert record["user_message"] == "no, I meant the other one"
        assert cs.count() == 1

    def test_find_relevant_empty(self):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir="/tmp")
        assert cs.find_relevant("anything") == []

    def test_find_relevant_matches(self, tmp_path):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir=str(tmp_path))
        cs.extract_correction("s1", "no, the file is in /etc/config", "")
        results = cs.find_relevant("where is the config file")
        assert len(results) >= 1
        assert "file" in results[0]["about"] or "config" in results[0]["about"]

    def test_to_context_string_returns_empty_when_no_match(self, tmp_path):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir=str(tmp_path))
        assert cs.to_context_string("hello") == ""

    def test_to_context_string_returns_string_when_match(self, tmp_path):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir=str(tmp_path))
        cs.extract_correction("s1", "no, it's a list not a dict", "")
        result = cs.to_context_string("list vs dict")
        assert "Corrections from previous sessions" in result
        assert "list" in result or "dict" in result

    def test_save_and_load_roundtrip(self, tmp_path):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir=str(tmp_path))
        cs.extract_correction("s1", "wrong answer", "oops")
        assert cs.count() == 1

        # New instance loads saved
        cs2 = CorrectionStore(data_dir=str(tmp_path))
        assert cs2.count() == 1

    def test_clear(self, tmp_path):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir=str(tmp_path))
        cs.extract_correction("s1", "wrong", "")
        cs.clear()
        assert cs.count() == 0

    def test_detect_behavioral_correction(self):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir="/tmp")
        assert cs.detect_correction("stop doing that", assistant_message="I will search")
        assert cs.detect_correction("don't say that", assistant_message="I understand")

    def test_extract_about_cleans_markers(self):
        from backend.core.self_learning.corrections import CorrectionStore
        assert "the answer" in CorrectionStore._extract_about("no, the answer is 42")
        assert "wrong path" in CorrectionStore._extract_about("actually, wrong path")

    def test_applied_count_increments(self, tmp_path):
        from backend.core.self_learning.corrections import CorrectionStore
        cs = CorrectionStore(data_dir=str(tmp_path))
        cs.extract_correction("s1", "no, it's Python", "")
        cs.find_relevant("Python")
        # reload to verify applied_count persisted
        cs2 = CorrectionStore(data_dir=str(tmp_path))
        assert cs2._corrections[0]["applied_count"] >= 1


class TestSkillImprover:
    def test_init_no_metrics(self):
        from backend.core.self_learning.improvement import SkillImprover
        si = SkillImprover()
        assert si._metrics is None
        assert si._last_review is None

    def test_review_skills_returns_report_structure(self):
        from backend.core.self_learning.improvement import SkillImprover
        si = SkillImprover()
        import asyncio
        report = asyncio.run(si.review_skills(force=True))
        assert "total" in report
        assert "used" in report
        assert "unused" in report
        assert "stale" in report
        assert "candidates" in report
        assert report["timestamp"] is not None

    def test_prune_stale_returns_empty_when_no_review(self):
        from backend.core.self_learning.improvement import SkillImprover
        si = SkillImprover()
        assert si.prune_stale() == []

    def test_get_improvement_suggestions_empty_when_no_review(self):
        from backend.core.self_learning.improvement import SkillImprover
        si = SkillImprover()
        assert si.get_improvement_suggestions() == []

    def test_is_stale_old_date(self):
        from backend.core.self_learning.improvement import SkillImprover
        old_skill = {"name": "test", "created": "2020-01-01T00:00:00"}
        assert SkillImprover._is_stale(old_skill)

    def test_is_stale_recent_date(self):
        from backend.core.self_learning.improvement import SkillImprover
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).isoformat()
        recent_skill = {"name": "test", "created": recent}
        assert not SkillImprover._is_stale(recent_skill)

    def test_is_stale_no_date(self):
        from backend.core.self_learning.improvement import SkillImprover
        assert not SkillImprover._is_stale({"name": "test"})

    def test_extract_created_from_frontmatter(self):
        from backend.core.self_learning.improvement import SkillImprover
        content = "---\ncreated: 2024-06-01T12:00:00\n---\n# Skill"
        assert SkillImprover._extract_created(content) == "2024-06-01T12:00:00"

    def test_extract_created_none_when_missing(self):
        from backend.core.self_learning.improvement import SkillImprover
        assert SkillImprover._extract_created("# Just a skill") is None

    def test_discover_skills_empty_dir(self, monkeypatch):
        from backend.core.self_learning.improvement import SkillImprover
        from backend.core.paths import SKILLS_DIR
        monkeypatch.setattr("backend.core.self_learning.improvement.SKILLS_DIR", Path("/nonexistent"))
        si = SkillImprover()
        assert si._discover_skills() == []


class TestPreferenceLearner:
    def test_init_defaults(self, tmp_path):
        from backend.core.self_learning.preferences import PreferenceLearner
        pl = PreferenceLearner(data_dir=str(tmp_path))
        assert pl.get_engagement_rate() == 0.5
        assert pl.get_frequent_topics() == []

    def test_observe_interaction_tracks_lengths(self, tmp_path):
        from backend.core.self_learning.preferences import PreferenceLearner
        pl = PreferenceLearner(data_dir=str(tmp_path))
        pl.observe_interaction("hello world", "Hi there!", user_followed_up=True)
        assert len(pl._response_lengths) == 1
        assert len(pl._engagements) == 1
        assert pl._engagements[0] == 1

    def test_observe_interaction_no_followup(self, tmp_path):
        from backend.core.self_learning.preferences import PreferenceLearner
        pl = PreferenceLearner(data_dir=str(tmp_path))
        pl.observe_interaction("hello", "Hi!", user_followed_up=False)
        assert pl._engagements[0] == 0

    def test_observe_interaction_extracts_topics(self, tmp_path):
        from backend.core.self_learning.preferences import PreferenceLearner
        pl = PreferenceLearner(data_dir=str(tmp_path))
        pl.observe_interaction("I love Python programming", "Great!", user_followed_up=False)
        topics = pl.get_frequent_topics()
        assert any("python" in t for t, _ in topics)

    def test_get_engagement_rate_calculated(self, tmp_path):
        from backend.core.self_learning.preferences import PreferenceLearner
        pl = PreferenceLearner(data_dir=str(tmp_path))
        pl.observe_interaction("a", "b", True)
        pl.observe_interaction("c", "d", False)
        pl.observe_interaction("e", "f", True)
        assert pl.get_engagement_rate() == 2 / 3

    def test_get_inferred_preferences_returns_dict(self, tmp_path):
        from backend.core.self_learning.preferences import PreferenceLearner
        pl = PreferenceLearner(data_dir=str(tmp_path))
        prefs = pl.get_inferred_preferences()
        assert isinstance(prefs, dict)

    def test_get_inferred_verbosity_requires_min_samples(self, tmp_path):
        from backend.core.self_learning.preferences import PreferenceLearner
        pl = PreferenceLearner(data_dir=str(tmp_path))
        assert pl._infer_verbosity() is None  # less than 3 samples
        pl.observe_interaction("a", "b", False)
        assert pl._infer_verbosity() is None  # still less than 3

    def test_infer_verbosity_concise(self, tmp_path):
        from backend.core.self_learning.preferences import PreferenceLearner
        pl = PreferenceLearner(data_dir=str(tmp_path))
        for _ in range(5):
            pl.observe_interaction("test", "short", user_followed_up=True)
        assert pl._infer_verbosity() == "concise"

    def test_reset_clears(self, tmp_path):
        from backend.core.self_learning.preferences import PreferenceLearner
        pl = PreferenceLearner(data_dir=str(tmp_path))
        pl.observe_interaction("hello", "world", True)
        assert len(pl._engagements) >= 1
        pl.reset()
        assert len(pl._engagements) == 0
        assert pl.get_frequent_topics() == []

    def test_save_and_load_roundtrip(self, tmp_path):
        from backend.core.self_learning.preferences import PreferenceLearner
        pl = PreferenceLearner(data_dir=str(tmp_path))
        pl.observe_interaction("hello Python", "Hi!", True)
        assert len(pl._response_lengths) == 1

        pl2 = PreferenceLearner(data_dir=str(tmp_path))
        assert len(pl2._response_lengths) == 1
