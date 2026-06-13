"""Per-turn quality evaluation (delta)."""

from typing import Optional


class DeltaEvaluator:
    """Scores a single interaction turn across quality axes."""

    AXES = ("response_time", "coherence", "relevance", "tool_success", "token_efficiency")

    def score(self, turn: dict) -> dict:
        """Return a dict of axis → float 0..1 plus an aggregate."""
        raw = {
            "response_time": self._score_response_time(turn.get("latency_ms", 0)),
            "coherence": self._score_coherence(turn.get("coherence", 0.5)),
            "relevance": self._score_relevance(turn.get("relevance", 0.5)),
            "tool_success": self._score_tool_success(turn.get("tool_errors", 0)),
            "token_efficiency": self._score_token_efficiency(
                turn.get("prompt_tokens", 0), turn.get("completion_tokens", 0)
            ),
        }
        raw["aggregate"] = sum(raw.values()) / len(raw)
        return raw

    # --- Private scoring helpers (each returns 0..1) ---

    def _score_response_time(self, latency_ms: int) -> float:
        if latency_ms <= 0:
            return 1.0
        if latency_ms < 2_000:
            return 1.0
        if latency_ms < 8_000:
            return max(0.0, 1.0 - (latency_ms - 2_000) / 6_000)
        return 0.0

    def _score_coherence(self, coherence: float) -> float:
        return max(0.0, min(1.0, coherence))

    def _score_relevance(self, relevance: float) -> float:
        return max(0.0, min(1.0, relevance))

    def _score_tool_success(self, errors: int) -> float:
        return 1.0 if errors == 0 else max(0.0, 1.0 - errors * 0.33)

    def _score_token_efficiency(self, prompt: int, completion: int) -> float:
        total = prompt + completion
        if total == 0:
            return 1.0
        ratio = completion / max(total, 1)
        # Penalise extremely long outputs for their prompt cost
        if ratio < 0.05:
            return 0.3
        if ratio > 0.9:
            return 0.5
        return 1.0
