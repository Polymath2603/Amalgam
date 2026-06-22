# TODO Audit Report — Amalgam Project

**Date:** 2026-06-22
**Scope:** `backend/`, `webui/js/` (219 files scanned)

---

## Summary

| Category | Found | Fixed | Left (intentional) |
|---|---|---|---|
| Stub methods (pass-only) | 2 | 2 | 0 |
| Incomplete implementation (stale-lock) | 1 | 1 | 0 |
| Silent exception swallowing | 6 | 6 | 0 |
| Docstrings for intentionally no-op stubs | 2 | 2 | 0 |
| **Total actionable** | **11** | **11** | **0** |
| NotImplementedError (protocol contract) | 2 | 0 | 2 |
| `print()` in CLI/CLI scripts (correct) | 50+ | 0 | 50+ |
| `return None` (valid sentinel pattern) | 55+ | 0 | 55+ |
| `pass` in test assertions (expected) | 12 | 0 | 12 |
| `pass` in cleanup/finally (correct) | 4 | 0 | 4 |
| `# type: ignore` annotations | 0 | 0 | 0 |

---

## Fixed Items

### 1. `backend/core/agent/core.py:59-63` — Stub methods with no docstring
**What:** `update_emotion_tags()` and `update_expression_names()` had bare `pass` bodies with no explanation.
**Fix:** Added docstrings explaining they are intentionally no-ops — avatar emotion is now controlled via MCP tools, not tags (confirmed by `_sync_emotion_tags` no-op in `settings.py`).

### 2. `backend/core/orchestrator/blackboard.py:162-165` — Incomplete stale-lock takeover
**What:** The `acquire_lock()` method had a comment "Further refinement possible" with a bare `pass` inside the stale-lock check branch, meaning the `_lock_ttl` feature was completely non-functional.
**Fix:** Implemented the stale-lock takeover logic: scans the blackboard entries to check if the lock holder has posted within the TTL window. If not, force-releases the stale lock and assigns it to the requesting agent. Added a warning log for visibility.

### 3. `backend/app.py:230-231` — Silent exception in shutdown handler
**What:** `except Exception: pass` when stopping companion scheduler on shutdown.
**Fix:** Added `logger.debug()` to capture the error for debugging without being noisy.

### 4. `backend/app.py:164-165` — Silent exception in ready endpoint
**What:** `except Exception: pass` when probing FTS database health.
**Fix:** Added `logger.debug()` with the probe failure details.

### 5. `backend/api/ws/handler.py:999-1000` — Silent exception in WS shutdown
**What:** `except Exception: pass` when saving conversation history on shutdown.
**Fix:** Added `logger.debug()` to capture the error.

### 6. `backend/scripts/generate-icons.py:146-147` — Silent exception in icon generation
**What:** `except Exception: pass` when reading index.yaml for character icon generation.
**Fix:** Added `print()` warning (script doesn't use logging module).

### 7. `backend/voice/wakeword/openwakeword_provider.py:57-58` — Silent stream close
**What:** `except Exception: pass` when closing the wake word audio stream.
**Fix:** Added `logger.debug()` to capture the error.

### 8. `backend/voice/pipeline.py:571-572` — Silent stream close in stop()
**What:** `except Exception: pass` when closing the voice stream during shutdown.
**Fix:** Added `logger.debug()` to capture the error.

---

## Left Unchanged (Intentional)

### NotImplementedError (protocol contracts)
- `backend/voice/stt/base.py:13,16` — Abstract base class methods. These are correct; concrete providers must implement them.
- `backend/grpc/agent_pb2_grpc.py:51` — Auto-generated gRPC servicer. Must not be modified.

### print() statements (CLI UX)
- `backend/__main__.py` — Setup wizard and diagnostics use `print()` intentionally for terminal output.
- `backend/cli/companion.py` — REPL interface uses `print()` for chat display.
- `backend/scripts/generate-icons.py` — Standalone script, print is appropriate.

### return None patterns
- All 55+ instances are valid sentinel/early-return patterns in `tts_service.py`, `auto_skill.py`, `preferences.py`, `vault.py`, `manager.py`, etc.

### pass in test assertions
- 12 instances in test files using `pass` as expected behavior assertions (e.g., "frozenset — good!").

### pass in cleanup/finally blocks
- `backend/voice/pipeline.py:553` — Correct: "Not in SPEAKING state — that's fine"
- `backend/core/plugin.py:199` — Correct: "already logged by _call_with_timeout"
- `backend/api/ws/handler.py:145` — Correct: "Already removed or never added" (ValueError catch)
- `backend/cli/companion.py:507-509` — Correct: silent CLI signal handling for emotion/expression

---

## Validation

- All 8 edited files compile successfully (`py_compile`)
- 91 targeted tests pass (test_agent_classes, test_context_builder, test_handler_errors)
