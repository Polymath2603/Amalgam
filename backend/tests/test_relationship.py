"""Tests for Relationship — pure functions and tmp_path."""
import pytest
from datetime import datetime, timezone, timedelta
from backend.core.relationship import Relationship, STAGES


@pytest.fixture
def rel(tmp_path):
    """Create a Relationship with a temporary database."""
    db_path = str(tmp_path / "test_rel.db")
    return Relationship(db_path=db_path)


class TestAnalyzeSentiment:
    def test_positive_text(self, rel):
        score = rel._analyze_sentiment("I love this amazing wonderful day")
        assert score > 0.7

    def test_negative_text(self, rel):
        score = rel._analyze_sentiment("This is terrible and awful and horrible")
        assert score < 0.3

    def test_neutral_text(self, rel):
        score = rel._analyze_sentiment("The weather is okay I suppose")
        assert 0.3 <= score <= 0.7

    def test_empty_string(self, rel):
        assert rel._analyze_sentiment("") == 0.5

    def test_whitespace_only(self, rel):
        assert rel._analyze_sentiment("   ") == 0.5

    def test_negation_handling(self, rel):
        """VADER should handle 'I don't hate this' as less negative than 'I hate this'."""
        neg = rel._analyze_sentiment("I hate this")
        negated = rel._analyze_sentiment("I don't hate this")
        assert negated > neg

    def test_exclamation_intensifier(self, rel):
        mild = rel._analyze_sentiment("This is great")
        intense = rel._analyze_sentiment("This is great!!!")
        assert intense >= mild

    def test_range_0_to_1(self, rel):
        for text in ["best day ever", "horrible nightmare", "meh", "ok", ""]:
            score = rel._analyze_sentiment(text)
            assert 0.0 <= score <= 1.0, f"Score {score} out of range for: {text}"


class TestAnalyzeDepth:
    def test_deep_text(self, rel):
        score = rel._analyze_depth("I think because I believe the reason why is important")
        assert score > 0.3

    def test_shallow_text(self, rel):
        score = rel._analyze_depth("ok")
        assert score < 0.2

    def test_empty_string(self, rel):
        assert rel._analyze_depth("") == 0.0

    def test_longer_text_increases_depth(self, rel):
        short = rel._analyze_depth("I think")
        long = rel._analyze_depth("I think because I believe that perhaps the reason is important")
        assert long >= short

    def test_range_0_to_1(self, rel):
        for text in ["I think because why how imagine", "ok", ""]:
            score = rel._analyze_depth(text)
            assert 0.0 <= score <= 1.0, f"Score {score} out of range for: {text}"


class TestCalculateStage:
    def test_stranger_default(self, rel):
        stats = rel._default_stats()
        assert rel._calculate_stage(stats) == "stranger"

    def test_intimate_stage(self, rel):
        stats = {
            "interaction_count": 100,
            "avg_sentiment": 0.8,
            "avg_depth": 0.6,
        }
        assert rel._calculate_stage(stats) == "intimate"

    def test_friend_stage(self, rel):
        stats = {
            "interaction_count": 25,
            "avg_sentiment": 0.4,
            "avg_depth": 0.2,
        }
        assert rel._calculate_stage(stats) == "friend"

    def test_acquaintance_stage(self, rel):
        stats = {
            "interaction_count": 5,
            "avg_sentiment": 0.1,
            "avg_depth": 0.0,
        }
        assert rel._calculate_stage(stats) == "acquaintance"

    def test_stage_requires_all_thresholds(self, rel):
        """High interactions but low sentiment should not reach high stage."""
        stats = {
            "interaction_count": 100,
            "avg_sentiment": 0.0,
            "avg_depth": 0.0,
        }
        stage = rel._calculate_stage(stats)
        assert stage in ("stranger", "acquaintance")

    def test_stages_ordered(self):
        names = [s[0] for s in STAGES]
        assert names == ["stranger", "acquaintance", "friend", "close_friend", "intimate"]


class TestApplyTimeDecay:
    def test_no_decay_recent(self, rel):
        stats = rel._default_stats()
        original_sentiment = stats["avg_sentiment"]
        rel._apply_time_decay(stats)
        assert stats["avg_sentiment"] == original_sentiment

    def test_decay_old_interaction(self, rel):
        stats = rel._default_stats()
        stats["avg_sentiment"] = 0.9
        stats["avg_depth"] = 0.8
        stats["last_interaction"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        rel._apply_time_decay(stats)
        assert stats["avg_sentiment"] < 0.9
        assert stats["avg_sentiment"] > 0.5
        assert stats["avg_depth"] < 0.8

    def test_decay_polarity_preserved(self, rel):
        """Negative sentiment should decay toward 0.5 from below."""
        stats = rel._default_stats()
        stats["avg_sentiment"] = 0.2
        stats["last_interaction"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        rel._apply_time_decay(stats)
        assert stats["avg_sentiment"] > 0.2


class TestDefaultStats:
    def test_has_all_fields(self, rel):
        stats = rel._default_stats()
        for key in ["interaction_count", "avg_sentiment", "avg_depth",
                     "total_words_user", "total_words_assistant",
                     "last_interaction", "created_at"]:
            assert key in stats

    def test_initial_values(self, rel):
        stats = rel._default_stats()
        assert stats["interaction_count"] == 0
        assert stats["avg_sentiment"] == 0.5
        assert stats["total_words_user"] == 0
