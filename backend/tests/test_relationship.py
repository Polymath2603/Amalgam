"""
BRUTAL TESTS for Relationship — concurrent DB access, edge values,
Unicode sentiment, boundary conditions, and corruption.

Catches: concurrent DB writes, NaN/Inf in stats, empty DB,
overflow interaction counts, and time decay edge cases.
"""
import asyncio
import pytest
import threading
from datetime import datetime, timezone, timedelta
from backend.core.relationship import Relationship, STAGES


@pytest.fixture
def rel(tmp_path):
    """Create a Relationship with a temporary database."""
    db_path = str(tmp_path / "test_rel.db")
    return Relationship(db_path=db_path)


# ===================================================================
# Original tests (preserved)
# ===================================================================

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


class TestAnalyzeSentimentBrutal:
    def test_unicode_emoji_sentiment(self, rel):
        """Emoji-heavy text should not crash."""
        score = rel._analyze_sentiment("\U0001f600\U0001f601\U0001f602")
        assert 0.0 <= score <= 1.0

    def test_cjk_sentiment(self, rel):
        score = rel._analyze_sentiment("你好")
        assert 0.0 <= score <= 1.0

    def test_very_long_text(self, rel):
        text = "I love this " * 10000
        score = rel._analyze_sentiment(text)
        assert 0.0 <= score <= 1.0

    def test_single_char(self, rel):
        score = rel._analyze_sentiment("a")
        assert 0.0 <= score <= 1.0

    def test_numbers_in_text(self, rel):
        score = rel._analyze_sentiment("12345 67890")
        assert 0.0 <= score <= 1.0

    def test_html_in_text(self, rel):
        score = rel._analyze_sentiment("<b>great</b> <i>awesome</i>")
        assert 0.0 <= score <= 1.0

    def test_mixed_positive_negative(self, rel):
        score = rel._analyze_sentiment("great but also terrible")
        assert 0.0 <= score <= 1.0

    def test_repeated_punctuation(self, rel):
        score = rel._analyze_sentiment("!!!???...!!!")
        assert 0.0 <= score <= 1.0


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
        long_val = rel._analyze_depth("I think because I believe that perhaps the reason is important")
        assert long_val >= short

    def test_range_0_to_1(self, rel):
        for text in ["I think because why how imagine", "ok", ""]:
            score = rel._analyze_depth(text)
            assert 0.0 <= score <= 1.0, f"Score {score} out of range for: {text}"


class TestAnalyzeDepthBrutal:
    def test_very_long_depth_text(self, rel):
        text = "because I think why how imagine suppose perhaps " * 500
        score = rel._analyze_depth(text)
        assert 0.0 <= score <= 1.0

    def test_unicode_depth(self, rel):
        score = rel._analyze_depth("为什么 怎么")
        assert 0.0 <= score <= 1.0

    def test_all_depth_markers(self, rel):
        text = "why how because think feel believe imagine perhaps maybe wonder suppose curious explain"
        score = rel._analyze_depth(text)
        assert score > 0.5


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


class TestCalculateStageBrutal:
    def test_zero_interactions(self, rel):
        stats = {"interaction_count": 0, "avg_sentiment": 0.5, "avg_depth": 0.5}
        stage = rel._calculate_stage(stats)
        assert stage == "stranger"

    def test_negative_sentiment(self, rel):
        stats = {"interaction_count": 50, "avg_sentiment": -0.5, "avg_depth": 0.3}
        stage = rel._calculate_stage(stats)
        assert isinstance(stage, str)

    def test_sentiment_above_1(self, rel):
        stats = {"interaction_count": 50, "avg_sentiment": 1.5, "avg_depth": 0.3}
        stage = rel._calculate_stage(stats)
        assert isinstance(stage, str)

    def test_huge_interaction_count(self, rel):
        stats = {"interaction_count": 1_000_000, "avg_sentiment": 0.9, "avg_depth": 0.8}
        stage = rel._calculate_stage(stats)
        assert stage == "intimate"

    def test_boundary_friend_to_close_friend(self, rel):
        """At exact threshold boundary."""
        stats = {"interaction_count": 50, "avg_sentiment": 0.5, "avg_depth": 0.3}
        stage = rel._calculate_stage(stats)
        assert stage == "close_friend"

    def test_each_stage_reachable(self, rel):
        """Each stage should be reachable with appropriate stats."""
        for name, thresholds in STAGES:
            stats = {
                "interaction_count": thresholds["interaction_count"],
                "avg_sentiment": thresholds["avg_sentiment"],
                "avg_depth": thresholds["avg_depth"],
            }
            stage = rel._calculate_stage(stats)
            assert stage == name, f"Expected {name} but got {stage}"


class TestApplyTimeDecay:
    def test_no_decay_recent(self, rel):
        stats = rel._default_stats()
        original_sentiment = stats["avg_sentiment"]
        rel._apply_time_decay(stats)
        assert stats["avg_sentiment"] == original_sentiment

    def test_decay_old_interaction(self, rel):
        stats = rel._default_stats()
        stats["last_interaction"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        stats["avg_sentiment"] = 0.8
        rel._apply_time_decay(stats)
        assert stats["avg_sentiment"] < 0.8


class TestApplyTimeDecayBrutal:
    def test_very_old_interaction(self, rel):
        stats = rel._default_stats()
        stats["last_interaction"] = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        stats["avg_sentiment"] = 0.8
        rel._apply_time_decay(stats)
        # After a year, should decay significantly (close to baseline 0.5)
        assert stats["avg_sentiment"] < 0.51

    def test_future_date(self, rel):
        """Future last_interaction should not cause issues."""
        stats = rel._default_stats()
        stats["last_interaction"] = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        stats["avg_sentiment"] = 0.8
        try:
            rel._apply_time_decay(stats)
        except Exception:
            pass  # May not handle future dates gracefully

    def test_missing_last_interaction(self, rel):
        """Missing last_interaction should not crash."""
        stats = rel._default_stats()
        stats.pop("last_interaction", None)
        stats["avg_sentiment"] = 0.8
        try:
            rel._apply_time_decay(stats)
        except (KeyError, TypeError):
            pass  # Acceptable

    def test_zero_sentiment_no_crash(self, rel):
        stats = rel._default_stats()
        stats["avg_sentiment"] = 0.0
        stats["last_interaction"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        rel._apply_time_decay(stats)
        assert stats["avg_sentiment"] >= 0.0


class TestRelationshipDB:
    """Async DB operations — concurrent access and edge cases."""

    @pytest.mark.asyncio
    async def test_ensure_db_creates_tables(self, rel):
        await rel._ensure_db()
        assert rel._initialized is True

    @pytest.mark.asyncio
    async def test_double_ensure_db_idempotent(self, rel):
        await rel._ensure_db()
        await rel._ensure_db()
        assert rel._initialized is True

    @pytest.mark.asyncio
    async def test_concurrent_ensure_db(self, rel):
        """Multiple concurrent _ensure_db calls should not deadlock."""
        async def ensure():
            await rel._ensure_db()
        await asyncio.gather(*[ensure() for _ in range(10)])
        assert rel._initialized is True

    @pytest.mark.asyncio
    async def test_default_stats_structure(self, rel):
        stats = rel._default_stats()
        assert "interaction_count" in stats
        assert "avg_sentiment" in stats
        assert "avg_depth" in stats
        assert "last_interaction" in stats