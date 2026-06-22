# Test Report

**Date:** 2026-06-22 (batch 1 verification)  
**Project:** /home/leonardo/Workplace/k

## Summary

| Metric | Count |
|--------|-------|
| Total tests collected | 702 |
| Passed | 697 |
| Skipped | 5 |
| Failed | 0 |
| Errors | 0 |

## Fast Tests (via `run_fast_tests.sh`)

```bash
python3 -m pytest backend/tests/ -q --tb=short -k "not add_turn_100 and not add_turn_concurrent and not uniqueness"
```

- **Collected:** 699 (3 deselected as slow)
- **Passed:** 694
- **Skipped:** 5
- **Failed:** 0

## Slow Tests (via `run_slow_tests.sh`)

```bash
python3 -m pytest backend/tests/ -v --tb=short -k "add_turn_100 or add_turn_concurrent or uniqueness"
```

- **Collected:** 3
- **Passed:** 3
| `test_start_session_uniqueness` | PASSED |
| `test_add_turn_100_messages`    | PASSED |
| `test_add_turn_concurrent`      | PASSED |
- **Failed:** 0

## Syntax Checks

- **JavaScript (33 files):** All passed (`node --check`)
  - `webui/js/modules/` (17 files): api-client, companion, config, health, history, markdown, mcp-command, mcp, memory-graph, settings, settings-schema, setup-wizard, state, tts, utils, voice, ws
  - `webui/js/` (16 files): adaptive-lipsync, advanced-lipsync, animation-manager, app, audio-utils, avatar, custom-select, frequency-analyzer, i18n, idle-manager, metrics, sprite-avatar, swarm, viseme-scheduler, visemes, vrm-animation

## Scripts Created

| Script | Purpose |
|--------|---------|
| `run_fast_tests.sh` | Runs fast tests (excludes slow stress tests) |
| `run_slow_tests.sh` | Runs slow stress tests (100 messages, concurrent, uniqueness) |

## Fixes Applied (from batch 1)

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

## Files Modified (batch 1)

1. `backend/core/utils/tokens.py` — Fixed edge cases in truncation and message budget selection
2. `backend/core/relationship.py` — Fixed VADER hang on long inputs
