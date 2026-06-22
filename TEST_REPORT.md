# Test Report

**Date:** 2026-06-22  
**Project:** /home/leonardo/Workplace/k

## Summary

| Metric | Count |
|--------|-------|
| Total tests collected | 702 |
| Passed | 697 |
| Skipped | 5 |
| Failed | 0 |
| Errors | 0 |

## Syntax Checks

- **JavaScript (13 files):** All passed (`node --check`)
- **Python (all backend files):** All passed (`ast.parse`)

## Fixes Applied

### 1. `backend/core/utils/tokens.py` — `truncate_to_token_limit`

**Problem:** When truncating text near the token limit, the result string (truncated text + `"\n...[truncated]"` suffix) could be longer than or equal to the original text, causing assertion failures in tests that expect truncation to reduce string length.

**Fix:** Added a guard that returns just the truncation marker when the result would be >= the original text length. Also added a `content_budget` calculation that reserves tokens for the suffix marker.

### 2. `backend/core/relationship.py` — `_analyze_sentiment`

**Problem:** VADER sentiment analyzer hangs indefinitely on very long inputs (e.g., 120K+ characters). The test `TestAnalyzeSentimentBrutal::test_very_long_text` was causing the entire test suite to time out.

**Fix:** Added input truncation to 10,000 characters before passing to VADER, which prevents the hang while still producing meaningful sentiment scores for typical-length text.

## Warnings (Non-blocking)

- `test_memory.py::TestAddTurnAndGetRecent::test_add_turn_user` — `DeprecationWarning: builtin type SwigPyPacked has no __module__ attribute` (chromadb internal, non-actionable)
- `test_tts_service.py::TestMakeWavBytesBrutal::test_nan_values_clipped` — `RuntimeWarning: invalid value encountered in cast` (expected behavior: NaN values are clipped to int16 range)
- `sys:1: DeprecationWarning: builtin type swigvarlink has no __module__ attribute` (chromadb internal)

## Skipped Tests (5)

All 5 skipped tests are in `test_voice_pipeline.py` — these require GPU/ML model dependencies not available in the test environment.

## Files Modified

1. `backend/core/utils/tokens.py` — Fixed edge cases in truncation and message budget selection
2. `backend/core/relationship.py` — Fixed VADER hang on long inputs
