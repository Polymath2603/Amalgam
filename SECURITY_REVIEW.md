# Security Review Report

**Reviewed:** 2026-06-22  
**Scope:** Files changed in the last 5 commits (`HEAD~5..HEAD`)  
**Reviewer:** Jcode automated security agent  

---

## Summary

| Severity | Found | Fixed | Remaining |
|----------|-------|-------|-----------|
| CRITICAL | 2 | 2 | 0 |
| HIGH     | 1 | 1 | 0 |
| MEDIUM   | 4 | 0 | 4 |
| LOW      | 5 | 0 | 5 |
| **Total**| **12** | **3** | **9** |

All CRITICAL and HIGH issues have been fixed in this review.

---

## CRITICAL Issues (Fixed)

### C1: Path Traversal in Character Asset Endpoint
- **File:** `backend/app.py` — `serve_character_asset()`
- **Impact:** An attacker can read arbitrary files from the server filesystem via `GET /characters/../../../etc/passwd` or similar path sequences.
- **Root Cause:** `CHARACTERS_DIR / file_path` was used directly without path sanitization.
- **Fix Applied:** Added `.resolve()` and prefix check to ensure the resolved path stays within `CHARACTERS_DIR`. Requests escaping the directory now return HTTP 403.

### C2: Path Traversal in Catch-All Static File Route
- **File:** `backend/app.py` — `serve_webui()`
- **Impact:** The catch-all `/{path}` route could serve any file on the filesystem (e.g., `GET /../../../etc/shadow`), potentially leaking sensitive data or application source.
- **Root Cause:** `WEBUI_DIR / path` was used directly without path sanitization.
- **Fix Applied:** Added `.resolve()` and prefix check. Requests escaping `WEBUI_DIR` now return HTTP 403.

---

## HIGH Issues (Fixed)

### H1: Unrestricted Settings Write via Slash Command
- **File:** `backend/api/ws/handler.py` — `handle_slash_command("settings", ...)`
- **Impact:** Any WS client could overwrite any settings key (including `provider.{name}.api_key`, `voice.elevenlabs.api_key`, etc.) via `/settings provider.gemini.api_key sk-...`. This allows credential theft or provider hijacking.
- **Fix Applied:** Added an allowlist of safe settings keys. Attempting to write disallowed keys returns a helpful error message directing users to the Settings UI.

---

## MEDIUM Issues (Report Only)

### M1: No Authentication on API Endpoints
- **Files:** `backend/app.py`, `backend/api/routes/companion.py`, `backend/api/routes/setup.py`
- **Description:** All REST API endpoints and the WebSocket handler lack authentication. Anyone on the network can:
  - Read/modify settings (including API keys)
  - Trigger companion messages
  - View/modify memory and conversation data
  - Access the setup wizard
- **Recommendation:** Add a bearer token or session-based auth middleware. At minimum, the app should generate a random token on first start and require it for API access. The `CORS_ORIGINS` whitelist helps for browser clients but does not protect the API itself.

### M2: WebSocket Session Spoofing via `session_id` Override
- **File:** `backend/api/ws/handler.py` — `run()` method, `user_message` handler
- **Description:** The client can supply an arbitrary `session_id` via `data.get("session_id")`, which is passed to `memory().set_current_session(sid)`. An attacker could manipulate the session context, potentially reading or overwriting another user's conversation memory.
- **Recommendation:** Generate session IDs server-side and refuse client-provided session IDs, or validate that the provided session ID belongs to the authenticated user.

### M3: Companion API Exposes LLM-Generated Content Without Sanitization
- **File:** `backend/api/routes/companion.py` — `trigger_companion_message()`
- **Description:** The `/api/companion/trigger` endpoint returns LLM-generated text directly. If the LLM is tricked via prompt injection, it could return malicious content that the frontend renders as assistant HTML.
- **Recommendation:** Sanitize/encode the response before returning it, or ensure the frontend escapes all LLM-generated content before rendering (see L1 below).

### M4: MCP Tool Retry Allows Arbitrary Tool Execution
- **File:** `backend/api/ws/handler.py` — `retry_tool` handler
- **Description:** The `retry_tool` message handler calls `mcp_client.call_tool(tool_name, tool_args)` with client-supplied `tool_name` and `tool_args`. While MCP permission levels exist, the `full` permission level allows unrestricted tool execution. A malicious client on the local network could trigger dangerous tool calls.
- **Recommendation:** Validate tool names against a known registry before execution. Ensure the permission level defaults to `confirm` (it does currently).

---

## LOW Issues (Report Only)

### L1: Frontend innerHTML Usage Audit
- **Files:** `webui/js/modules/ws.js`, `webui/js/modules/settings.js`, `webui/js/modules/history.js`, `webui/js/modules/mcp.js`, `webui/js/modules/markdown.js`, `webui/js/modules/memory-graph.js`, `webui/js/modules/mcp-command.js`, `webui/js/modules/setup-wizard.js`, `webui/js/app.js`
- **Description:** The codebase has ~106 `innerHTML` assignments across 18 files. The good news is that `escHtml()` is used consistently for user-supplied values (chat messages, settings values, filenames, error messages, etc.). The `formatMessage()` function in `markdown.js` properly escapes before applying markdown transforms. `showToast()` in `utils.js` escapes all parameters.
- **Remaining Risk:** `ws.js` line 293 uses `el.innerHTML = formatMessage(text)` on streamed LLM output. While `formatMessage()` calls `renderMarkdown()` which escapes HTML entities, the tool-call card injection pattern (`[TOOL_CALL:...]`) creates HTML from regex-captured names without escaping `data-tool` attributes. If an LLM produces a tool call with a name containing `"`, it could inject arbitrary attributes.
- **Recommendation:** Apply `escHtml()` to the `name` and `args` captured in the `formatMessage` regex replacement for tool calls (currently done for display, but the `data-tool` attribute value is unescaped).

### L2: CORS Configuration Allows Broad Origins
- **File:** `backend/app.py`
- **Description:** Default CORS origins include `localhost:8000`, `localhost:5173`, `localhost:3000`, and `tauri://localhost`. These are reasonable for development, but the `AMALGAM_CORS_ORIGINS` environment variable allows arbitrary origins to be set.
- **Recommendation:** Document that `AMALGAM_CORS_ORIGINS` should be treated as a security-sensitive configuration. Consider restricting it further for production deployments.

### L3: Rate Limiter Uses In-Memory State
- **File:** `backend/app.py` — `_RateLimitMiddleware`
- **Description:** The per-IP rate limiter stores state in a Python dict (`_in_flight_requests`). In multi-worker deployments (e.g., with gunicorn), each worker would have independent counters, effectively multiplying the rate limit.
- **Recommendation:** For production multi-worker deployments, use a shared store (e.g., Redis) for rate limiting.

### L4: Companion Scheduler LLM Prompt Injection Surface
- **File:** `backend/core/companion/scheduler.py`
- **Description:** The `_build_companion_prompt()` method injects `personality_notes` from user-configurable settings directly into the system prompt. If a user (or attacker with API access) sets `companion.personality_notes` to a prompt injection payload, it could manipulate the companion's behavior. This is a self-inflicted attack vector (the user can already configure the character system prompt), but worth noting since the companion runs autonomously in the background.
- **Recommendation:** This is inherent to the "user controls their own AI" design. Consider documenting the trust boundary.

### L5: `_normalize_error` Leaks Internal Error Details
- **File:** `backend/api/ws/handler.py`
- **Description:** When an error doesn't match any known pattern, `_normalize_error` returns the raw error text to the client. This could leak internal implementation details, file paths, or stack trace fragments.
- **Recommendation:** For non-matching errors, return a generic "An unexpected error occurred" message and log the full error server-side only.

---

## Positive Findings

The codebase demonstrates several good security practices:

1. **Consistent HTML Escaping:** The `escHtml()` function in `utils.js` is well-implemented and used pervasively throughout the frontend.
2. **Markdown Rendering:** `renderMarkdown()` in `markdown.js` escapes HTML entities before applying markdown transformations, preventing XSS through markdown content.
3. **SQL Injection Protection:** `metrics.py` uses parameterized queries throughout (`aiosqlite` with `?` placeholders).
4. **Blackboard Lock Safety:** `blackboard.py` uses `asyncio.Lock()` consistently for all shared state access, preventing race conditions.
5. **Rate Limiting:** A per-IP sliding window rate limiter is in place.
6. **Input Validation:** Pydantic models are used for API request validation in `setup.py` and `companion.py`.
7. **Thread Safety:** `pending_tasks` in `ChatSession` has proper cleanup with `try/except ValueError` guards.
8. **No Hardcoded Secrets:** All API keys are stored in settings or environment variables, with empty-string defaults in code.
9. **CORS Configuration:** Properly configured for local development with configurable override.

---

## Files Changed in This Review

| File | Changes |
|------|---------|
| `backend/app.py` | Added path traversal protection to `serve_character_asset()` and `serve_webui()` |
| `backend/api/ws/handler.py` | Added settings allowlist for `/settings` command; added character name sanitization for `/character` command |
