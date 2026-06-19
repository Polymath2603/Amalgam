"""Per-turn quality evaluation (delta)."""


class DeltaEvaluator:
    """Scores a single interaction turn across quality axes.

    Each axis returns a float in [0.0, 1.0].
    The aggregate is an unweighted average of all axes.
    """

    AXES = ("response_time", "coherence", "relevance", "tool_success", "token_efficiency")

    # ── Scoring thresholds (calibrated empirically) ──────────────
    _LATENCY_FAST_MS = 2_000          # ≤ this → perfect score
    _LATENCY_SLOW_MS = 8_000          # ≥ this → zero score
    _TOOL_ERROR_PENALTY = 0.33        # deducted per error
    _TOKEN_RATIO_VERY_LOW = 0.05      # completion / total below this → penalised
    _TOKEN_RATIO_VERY_HIGH = 0.9      # completion / total above this → penalised

    def score(self, turn: dict) -> dict:
        """Return a dict of axis → float 0..1 plus an aggregate.

        Raises TypeError if *turn* is not a dict.
        """
        if not isinstance(turn, dict):
            raise TypeError(f"Expected dict for turn, got {type(turn).__name__}")

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
        """Score latency: faster = better."""
        if latency_ms < self._LATENCY_FAST_MS:
            return 1.0
        if latency_ms < self._LATENCY_SLOW_MS:
            return max(0.0, 1.0 - (latency_ms - self._LATENCY_FAST_MS)
                       / (self._LATENCY_SLOW_MS - self._LATENCY_FAST_MS))
        return 0.0

    def _score_coherence(self, coherence: float) -> float:
        return max(0.0, min(1.0, coherence))

    def _score_relevance(self, relevance: float) -> float:
        return max(0.0, min(1.0, relevance))

    def _score_tool_success(self, errors: int) -> float:
        return 1.0 if errors == 0 else max(0.0, 1.0 - errors * self._TOOL_ERROR_PENALTY)

    def _score_token_efficiency(self, prompt: int, completion: int) -> float:
        """Score the prompt/completion balance. Negative inputs are clamped to zero."""
        prompt = max(0, prompt)
        completion = max(0, completion)
        total = prompt + completion
        if total == 0:
            return 1.0
        ratio = completion / total
        # Penalise extremely long outputs for their prompt cost
        if ratio < self._TOKEN_RATIO_VERY_LOW:
            return 0.3
        if ratio > self._TOKEN_RATIO_VERY_HIGH:
            return 0.5
        return 1.0
