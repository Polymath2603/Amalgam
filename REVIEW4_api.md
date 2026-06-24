# REVIEW 4 — API Layer Audit

**Scope:** `backend/api/` — all 20 files  
**Goal:** Zero issues — dead imports, logic bugs, route conflicts, unreachable code  
**Audit method:** Static AST analysis + cross-reference verification + manual review

---

## RESULT: 19 issues remain ✗

Despite Round 3 fixes, the API layer is **not clean**. Categorised breakdown below.

---

## 1. DEAD IMPORTS (16 instances)

### routes/characters.py
| Line | Import | Why dead |
|------|--------|----------|
| 55 | `import os as _os` inside `get_animations()` | `_os` is never referenced; the function does pure string checks (`'..' in char_id`, `char_id.isprintable()`) |

### routes/metrics.py
| Line | Import | Why dead |
|------|--------|----------|
| 7 | `defaultdict` from `collections` | Only `deque` is used on line 19 |

### routes/push.py
| Line | Import | Why dead |
|------|--------|----------|
| 10 | `Optional` from `typing` | Neither request model uses `Optional` |

### routes/settings.py
| Line | Import | Why dead |
|------|--------|----------|
| 10 | `BUILTIN_VOICES` from `backend.core.config.settings` | Probably left over from an earlier route; never referenced in this file |
| 433 | `import re as _re` inside `get_settings_safe()` | The function only does dict iteration + masking with string methods; no regex used |

### routes/setup.py
| Line | Import | Why dead |
|------|--------|----------|
| 13 | `HTTPException` from `fastapi` | All setup routes return error dicts / `JSONResponse`, never raise `HTTPException` |

### routes/vault.py
| Line | Import | Why dead |
|------|--------|----------|
| 10 | `VAULT_DIR` from `backend.core.paths` | The vault operations go through `vault()` singleton; `VAULT_DIR` is never referenced |

### telegram.py
| Line | Import | Why dead |
|------|--------|----------|
| 5 | `import os` | Never referenced in the file |
| 8 | `import json` | Never referenced in the file |
| 10 | `Optional` from `typing` | No type annotation uses `Optional` |
| 12 | `Bot` from `telegram` | Only `Update` is used from that import |

### ws/handler.py
| Line | Import | Why dead |
|------|--------|----------|
| 12 | `Any` from `typing` | No type annotation in the file uses `Any` |
| 15 | `tts` from `backend.api.deps` | `tts()` is never called directly; the TTS work goes through `OrderedTTSScheduler` / `synthesize_now` from `tts_service` |
| 16 | `synthesize_sentence` from `backend.api.ws.tts_service` | Only `OrderedTTSScheduler` and `synthesize_now` are used |
| 17 | `TranslationService` from `backend.core.translation` | The top-level import is never referenced; `_get_translation_service()` does its own local import |
| 24 | `LLMProviderError` from `backend.core.llm.litellm_provider` | Only `RateLimitError` from that import is used |

---

## 2. DEAD EXPORTS IN `deps.py`

**File:** `backend/api/deps.py`

| Name | Consumed by API layer? |
|------|----------------------|
| `context_builder` | **No** — never imported by any `api/` file |
| `context_manager` | **No** — never imported by any `api/` file |

All other re-exports (`settings`, `llm`, `memory`, `vault`, `mcp`, `tts`, `agent`, `relationship`, `wakeword`, `get_shared`, `orchestrator`, `companion`) are consumed.

---

## 3. ROUTE ORDERING BUG — unreachable endpoint

**File:** `routes/memory.py`

```
Line 20:  @router.get("/api/memory/session/{session_id}")   ← catches "current"
Line 78:  @router.get("/api/memory/session/current")        ← NEVER MATCHES
```

`GET /api/memory/session/current` is **permanently shadowed** by the parameterized route at line 20. The dedicated `get_current_session_messages()` function is unreachable. (The shadowing route does handle `session_id == "current"` as a special case, so the behaviour is correct by accident — but the code at line 78 is dead.)

**Fix:** Move the `/api/memory/session/current` route above the `{session_id}` route, or merge the logic.

---

## 4. DEAD PARAMETERS

**File:** `ws/handler.py`, method `_handle_avatar_signal` (line 450)

```python
async def _handle_avatar_signal(self, sig_val, current_emotion, full_response, sentence_buffer, char_id):
```

The parameters `current_emotion`, `full_response`, and `sentence_buffer` are **never used** inside the method body. They are passed at every call site (line 262) but serve no purpose.

**Fix:** Remove the three unused parameters from the signature and the call site.

---

## Summary

| Category | Count |
|----------|-------|
| Dead imports | 16 |
| Dead exports (`deps.py`) | 2 |
| Route ordering (unreachable endpoint) | 1 |
| Dead parameters | 1 set (3 params) |
| **Total outstanding issues** | **19** |

The API layer is **not** completely clean. >99 % of the code is fine, but these 19 items should be cleaned up for a truly zero-issue pass.
