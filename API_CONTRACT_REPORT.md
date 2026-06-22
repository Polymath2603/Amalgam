# Amalgam API Contract Report

Generated: 2026-06-21  
Scope: Backend REST + WebSocket endpoints vs. Frontend consumption  
Codebase: `/home/leonardo/Workplace/k/`

---

## 1. REST Endpoint Map

### 1.1 Settings (`backend/api/routes/settings.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| GET | `/api/settings` | - | `{...settings}` | CORS | ✅ app.js, ws.js, settings.js, mcp.js |
| POST | `/api/settings` | `dict` (full settings) | `{status, voice}` | CORS | ✅ app.js |
| POST | `/api/settings/set` | `{key, value}` | `{status}` | CORS | ✅ voice.js, app.js, settings.js, setup-wizard.js |
| POST | `/api/settings/batch` | `{settings: {k: v, ...}}` | `{status, count}` | CORS | ✅ settings.js, mcp.js, mcp-command.js |
| GET | `/api/settings/get/{key}` | - | `{key, value}` | CORS | ✅ app.js |
| POST | `/api/settings/test/{provider}` | - | `{ok, latency_ms, error}` | CORS | ✅ settings.js, setup-wizard.js |
| GET | `/api/settings/safe` | - | `{...masked settings}` | CORS | ❌ Dead endpoint |
| POST | `/api/settings/reset?target=X` | - | `{status}` | CORS | ❌ Dead endpoint |

### 1.2 Characters & Assets (`backend/api/routes/characters.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| GET | `/api/characters` | - | `{id: {name, ...}, ...}` | CORS | ✅ settings.js, app.js |
| GET | `/api/characters/{id}` | - | character dict or 404 | CORS | ❌ Dead endpoint |
| GET | `/api/animations?char_id=X` | - | `{default: [...], character: [...]}` | CORS | ❌ Dead endpoint |
| GET | `/api/emotions` | - | `{emotions: [...]}` | CORS | ❌ Dead endpoint |
| GET | `/api/expressions?char_id=X` | - | `{expressions: [...]}` | CORS | ❌ Dead endpoint |
| GET | `/api/voices` | - | builtin voices list | CORS | ❌ Dead endpoint |
| GET | `/api/models/ollama` | - | `{models: [...]}` | CORS | ❌ (covered by generic) |
| GET | `/api/models/gemini` | - | `{models: [...]}` | CORS | ❌ (covered by generic) |
| GET | `/api/models/{provider}` | - | `{models: [...]}` | CORS | ✅ settings.js |

### 1.3 Commands (`backend/api/routes/commands.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| GET | `/api/commands` | - | `{commands: [...]}` | CORS | ✅ app.js |

### 1.4 MCP (`backend/api/routes/mcp.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| GET | `/api/mcp/servers` | - | `{servers: [{name, connected, ...}]}` | CORS | ✅ mcp.js, mcp-command.js |
| POST | `/api/mcp/servers` | `{servers: [...]}` | `{status, message}` | CORS | ❌ (frontend uses `/api/settings/batch` instead) |
| GET | `/api/mcp/tools` | - | `{tools: [...]}` | CORS | ✅ mcp.js |
| POST | `/api/shell/approve` | `{cmd, mode}` | `{status, mode, cmd}` | CORS | ✅ app.js |

### 1.5 Memory (`backend/api/routes/memory.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| GET | `/api/memory/sessions` | - | `{sessions: [...], current}` | CORS | ✅ history.js, app.js |
| GET | `/api/memory/session/{id}` | - | `{messages, session_id, exists}` | CORS | ✅ app.js |
| POST | `/api/memory/session/{id}/rename?new_title=X` | - | `{status, title}` | CORS | ❌ Dead endpoint |
| GET | `/api/memory/session/{id}/resume?turns=5` | - | `{messages}` | CORS | ❌ Dead endpoint |
| POST | `/api/memory/session/{id}/activate` | - | `{session_id, messages, status}` | CORS | ❌ Dead endpoint |
| DELETE | `/api/memory/session/{id}` | - | `{status}` | CORS | ✅ history.js, app.js |
| POST | `/api/memory/clear` | - | `{status}` | CORS | ✅ history.js |
| GET | `/api/memory/session/current` | - | `{session_id, messages}` | CORS | ✅ history.js |
| POST | `/api/memory/new-session` | - | `{session_id, status}` | CORS | ✅ history.js, app.js |
| GET | `/api/memory/search?q=X&scope=all` | - | `{results}` | CORS | ✅ history.js |

### 1.6 Metrics (`backend/api/routes/metrics.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| GET | `/api/metrics/turns?limit=50` | - | `{turns: [...]}` | CORS | ✅ metrics.js |
| GET | `/api/metrics/tool-stats?tool=X` | - | tool analytics or error | CORS | ❌ Dead endpoint |
| GET | `/api/metrics/tool-history?limit=50` | - | `{history: [...]}` | CORS | ✅ metrics.js |
| GET | `/api/metrics/summary` | - | `{total_turns, total_cost, ...}` | CORS | ✅ metrics.js |

### 1.7 Push Notifications (`backend/api/routes/push.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| POST | `/api/push/register` | `{token, platform, device_id}` | `{status}` | CORS | ❌ Dead endpoint |
| POST | `/api/push/unregister` | `{token}` | `{status}` | CORS | ❌ Dead endpoint |
| GET | `/api/push/tokens` | - | `{tokens: [...]}` | CORS | ❌ Dead endpoint |

### 1.8 Setup Wizard (`backend/api/routes/setup.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| GET | `/api/setup/status` | - | `{needs_setup, completed_steps, providers}` | CORS | ✅ app.js |
| POST | `/api/setup/step1` | `{provider, api_key, model}` | `{ok, provider, detail, error}` | CORS | ✅ setup-wizard.js |
| POST | `/api/setup/step2` | `{stt_engine, tts_engine, voice_input_enabled, voice_output_enabled}` | `{ok, tts_detail}` | CORS | ✅ setup-wizard.js |
| POST | `/api/setup/step3` | `{character, permission_level, companion_enabled, thinking_enabled}` | `{ok, setup_complete, character}` | CORS | ✅ setup-wizard.js |
| POST | `/api/setup/save` | `{provider, api_key, model}` | `{status}` | CORS | ❌ Dead endpoint |
| GET | `/api/providers` | - | `{providers: [...]}` | CORS | ✅ app.js, settings.js, setup-wizard.js |

### 1.9 TTS (`backend/api/routes/tts.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| POST | `/api/tts/preview` | `{text}` | `{audio (b64), format}` | CORS | ❌ Dead endpoint |

### 1.10 Vault & Rules (`backend/api/routes/vault.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| GET | `/api/rules` | - | `{content}` | CORS | ❌ Dead endpoint |
| POST | `/api/rules` | `{content}` | `{status}` | CORS | ❌ Dead endpoint |
| GET | `/api/vault/files` | - | `{files: [...]}` | CORS | ❌ Dead endpoint |
| GET | `/api/vault/files/{filename}` | - | `{name, content}` | CORS | ❌ Dead endpoint |
| POST | `/api/vault/files/{filename}` | `{content}` | `{status}` | CORS | ❌ Dead endpoint |
| DELETE | `/api/vault/files/{filename}` | - | `{status}` | CORS | ❌ Dead endpoint |
| GET | `/api/vault/search?q=X` | - | `{results, mode}` | CORS | ❌ Dead endpoint |

### 1.11 Relationship (`backend/api/routes/relationship.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| GET | `/api/relationship/{character_id}` | - | `{character_id, ...stats}` | CORS | ✅ app.js |

### 1.12 Companion (`backend/api/routes/companion.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| GET | `/api/companion/settings` | - | `{enabled, idle_check_delay, ...}` | CORS | ❌ Dead endpoint |
| POST | `/api/companion/settings` | `{enabled, idle_check_delay, ...}` | `{ok, settings}` | CORS | ❌ Dead endpoint |
| POST | `/api/companion/trigger` | - | `{ok, content}` | CORS | ❌ Dead endpoint |

### 1.13 Health (`backend/app.py`)

| Method | Path | Request Body | Response | Auth | Frontend Used |
|--------|------|-------------|----------|------|---------------|
| GET | `/api/health` | - | `{status, service, version, uptime, services}` | CORS | ✅ health.js |
| GET | `/ready` | - | `{status, db_ok}` | CORS | ❌ Dead endpoint |

---

## 2. WebSocket Message Map

**Endpoint:** `WS /ws/chat`

### 2.1 Client → Server Messages

| Message Type | Payload | Sent By | Backend Handled |
|-------------|---------|---------|-----------------|
| `client_hello` | `{capabilities, platform}` | ws.js | ✅ |
| `command` (voice_input_on) | `{type, command}` | voice.js, ws.js | ✅ |
| `command` (voice_input_off) | `{type, command}` | voice.js, ws.js | ✅ |
| `command` (voice_output_on) | `{type, command}` | ws.js | ✅ |
| `command` (voice_output_off) | `{type, command}` | ws.js | ✅ |
| `command` (speak) | `{type, command, text}` | app.js | ✅ |
| `command` (typing) | `{type, command}` | app.js | ❌ **Not handled** |
| `command` (stop_typing) | `{type, command}` | app.js | ❌ **Not handled** |
| `command` (mcp_config_update) | `{type, command, args}` | mcp-command.js | ❌ **Not handled** |
| `command` (avatar_set_visibility) | `{type, command, visible}` | (implicit) | ✅ |
| `command` (wake_word_on) | `{type, command}` | (voice pipeline) | ✅ |
| `command` (wake_word_off) | `{type, command}` | (voice pipeline) | ✅ |
| `slash_command` | `{type, command, args}` | app.js | ✅ |
| `user_message` | `{type, text, images?, session_id?}` | app.js, voice.js, ws.js | ✅ |
| `ping` | `{type}` | ws.js (heartbeat) | ✅ → `pong` |
| `idle_enter` | `{type}` | companion.js | ✅ |
| `idle_exit` | `{type}` | companion.js | ✅ |
| `idle_prompt_request` | `{type}` | app.js (avatar idle) | ✅ |
| `avatar_life_event` | `{type, event}` | avatar.js | ✅ |
| `interrupt` | `{type, action: 'stop_audio_and_animation'}` | (JS) | ✅ |
| `retry_tool` | `{type, tool, ...}` | markdown.js | ❌ **Not handled** |

### 2.2 Server → Client Messages

| Message Type | Payload | Sent By | Frontend Handled |
|-------------|---------|---------|-----------------|
| `server_hello` | `{platform, capabilities}` | handler.py | ❌ **No handler in ws.js** |
| `chat_start` | `{role}` | handler.py | ✅ ws.js |
| `chat_append` | `{role, text, finished, error?, session_id?}` | handler.py | ✅ ws.js |
| `emotion` | `{emotion}` | handler.py | ✅ ws.js |
| `expression` | `{expression}` | handler.py | ✅ ws.js |
| `voice_state` | `{state}` | handler.py | ✅ ws.js |
| `tts_audio` | `{audio, format, duration, sentence_idx, emotion, viseme_schedule?}` | tts_service.py | ✅ ws.js |
| `tts_error` | `{message, sentence_idx}` | tts_service.py | ✅ ws.js |
| `tts_interrupt` | `{}` | handler.py | ✅ ws.js |
| `animation` | `{name, url}` | handler.py | ✅ ws.js |
| `roleplay` | `{text, animation_url}` | handler.py | ✅ ws.js (anim only) |
| `thinking` | `{text}` | handler.py | ✅ ws.js |
| `tool_call` | `{text}` | handler.py | ✅ ws.js |
| `permission_request` | `{command}` | handler.py | ✅ ws.js |
| `wake_word_state` | `{enabled, error?}` | handler.py | ❌ **No handler in ws.js** |
| `viseme` | `{value}` | handler.py | ❌ **No handler in ws.js** |
| `visibility` | `{visible}` | handler.py | ✅ ws.js |
| `idle_prompt` | `{text}` | handler.py | ✅ ws.js |
| `theme_change` | `{theme}` | handler.py | ✅ ws.js |
| `swarm_update` | `{data}` | handler.py | ✅ ws.js → window.handleSwarmUpdate |
| `service_status` | `{services}` | (health) | ✅ ws.js |
| `settings_change` | `{settings}` | (push) | ✅ ws.js |
| `companion` | `{content}` | companion scheduler | ✅ ws.js |
| `user_message_from_voice` | `{text}` | handler.py | ✅ ws.js |
| `pong` | `{}` | handler.py | ✅ ws.js (heartbeat) |
| `tool_call_update` | `{tool_call_id, status, result}` | handler.py | ✅ ws.js |
| `interrupt` | `{action}` | handler.py | ✅ ws.js |
| `avatar_life_event` | `{event}` | (frontend only) | ✅ ws.js (but backend never sends) |

---

## 3. Mismatches & Issues

### 3.1 Frontend Sends WS Messages Backend Does NOT Handle

| Issue | Frontend Source | Message | Severity |
|-------|----------------|---------|----------|
| **`typing` command ignored** | app.js:412 | `{type: 'command', command: 'typing'}` | 🟡 Medium |
| **`stop_typing` command ignored** | app.js:415,597 | `{type: 'command', command: 'stop_typing'}` | 🟡 Medium |
| **`mcp_config_update` command ignored** | mcp-command.js:197 | `{type: 'command', command: 'mcp_config_update', args}` | 🟡 Medium |
| **`retry_tool` message type unknown** | markdown.js:137 | `{type: 'retry_tool', tool: ...}` | 🔴 High |

The `typing` and `stop_typing` commands silently fall through the `handle_command` if/elif chain with no response. The frontend expects typing indicators but never receives them from these commands.

### 3.2 Backend Sends WS Messages Frontend Does NOT Handle

| Issue | Backend Source | Message | Severity |
|-------|---------------|---------|----------|
| **`server_hello` not consumed** | handler.py:917 | `{type: 'server_hello', platform, capabilities}` | 🟡 Medium |
| **`wake_word_state` not consumed** | handler.py:431-439 | `{type: 'wake_word_state', enabled, error?}` | 🟢 Low |
| **`viseme` not consumed** | handler.py:265 | `{type: 'viseme', value}` | 🟢 Low |
| **`avatar_life_event` handler is dead** | ws.js:361-362 | `{type: 'avatar_life_event', event}` | 🟡 Medium |

The `server_hello` response is sent but the frontend never reads it — the client_hello is fire-and-forget.

### 3.3 Dead REST Backend Endpoints (Never Called by Frontend)

**Critical (should likely be removed or frontend should integrate):**

| Endpoint | Purpose | Notes |
|----------|---------|-------|
| `GET /api/settings/safe` | Masked settings display | May be useful for admin/debug UIs |
| `POST /api/settings/reset` | Reset settings section | Settings panel has no "Reset" button |
| `POST /api/companion/trigger` | Manual companion message | Companion is auto-scheduled only |
| `GET /api/companion/settings` | Read companion config | Companion settings not in UI panel |
| `POST /api/companion/settings` | Write companion config | Companion settings not in UI panel |
| `POST /api/tts/preview` | TTS voice preview | Settings panel has no "Test Voice" button |
| `GET /api/setup/save` | Legacy setup save | Superseded by step1-step3 flow |
| `POST /api/mcp/servers` | Direct MCP config | Frontend uses `/api/settings/batch` instead |

**Non-critical (server-side features with no UI):**

| Endpoint | Purpose |
|----------|---------|
| `GET /api/emotions` | Emotion listing |
| `GET /api/expressions` | VRM expression listing |
| `GET /api/voices` | Voice listing |
| `GET /api/animations` | VRMA animation listing |
| `GET /api/characters/{id}` | Single character lookup |
| `GET /api/models/ollama` | Ollama-specific model list |
| `GET /api/models/gemini` | Gemini-specific model list |
| `GET /api/rules` | Read rules.md |
| `POST /api/rules` | Write rules.md |
| `GET /api/vault/files` | List vault files |
| `GET /api/vault/files/{filename}` | Read vault file |
| `POST /api/vault/files/{filename}` | Write vault file |
| `DELETE /api/vault/files/{filename}` | Delete vault file |
| `GET /api/vault/search` | Search vault files |
| `POST /api/push/register` | Register push token |
| `POST /api/push/unregister` | Unregister push token |
| `GET /api/push/tokens` | List push tokens |
| `GET /api/metrics/tool-stats` | Tool analytics |
| `POST /api/memory/session/{id}/rename` | Rename session |
| `GET /api/memory/session/{id}/resume` | Resume session turns |
| `POST /api/memory/session/{id}/activate` | Activate session |
| `GET /ready` | Readiness probe |

### 3.4 Backend WS Slash Commands with No Frontend UI

These slash commands are handled in the backend but have no visible UI button or help grouping:

| Command | Purpose |
|---------|---------|
| `/plan create/list/status/run/cancel` | Orchestrator plan management |
| `/profile <name>` | Switch settings profile |
| `/permission <level>` | Set permission level |
| `/companion` | Toggle companion mode (but only toggles voice, not companion.enabled) |

### 3.5 Field-Level Mismatches

| Issue | Details | Severity |
|-------|---------|----------|
| **`/companion` slash command misconfigured** | handler.py:607-616 toggles `voice.input_enabled` and `voice.output_enabled` instead of `companion.enabled` | 🔴 High |
| **`POST /api/memory/session/{id}/rename` expects query param** | Backend uses `new_title: str` as query param, but no frontend calls it | 🟡 Medium |
| **MCP settings saved via wrong endpoint** | Frontend mcp.js toggles send to `/api/settings/batch` with nested `mcp.servers`, but `POST /api/mcp/servers` is the dedicated endpoint | 🟢 Low |

### 3.6 Auth Concerns

| Issue | Details | Severity |
|-------|---------|----------|
| **No authentication** | All endpoints are open (CORS-only protection). No JWT, session cookies, or API tokens. | 🟡 Medium (by design for local app) |
| **`GET /api/push/tokens` exposes all tokens** | Admin-only endpoint has no auth guard | 🟡 Medium |
| **Rate limiting is IP-based only** | 120 req/min per IP, trivially bypassable | 🟢 Low |

---

## 4. Summary Statistics

| Metric | Count |
|--------|-------|
| Total REST endpoints (backend) | **65** |
| Total REST endpoints used by frontend | **38** |
| Dead REST endpoints (backend only) | **27** (42%) |
| Total WS message types (client→server) | **11** unique types |
| Total WS message types (server→client) | **29** unique types |
| Unhandled client→server WS messages | **4** (typing, stop_typing, mcp_config_update, retry_tool) |
| Unhandled server→client WS messages | **4** (server_hello, wake_word_state, viseme, avatar_life_event handler) |

---

## 5. Recommendations

### High Priority

1. **Fix `retry_tool` handling** — Frontend markdown.js sends `{type: 'retry_tool'}` but the backend ignores it. Either add handler or remove the UI retry button.

2. **Fix `/companion` slash command** — It toggles `voice.input_enabled`/`voice.output_enabled` instead of `companion.enabled`. This is a functional bug.

3. **Add `typing`/`stop_typing` command handling** — Frontend sends these to show typing indicators but backend ignores them. Either implement server-side typing detection or remove the commands from the frontend.

4. **Add `mcp_config_update` handling** — The `/mcp` panel sends config updates via WS but the backend doesn't process them. MCP toggle changes only persist via the REST settings/batch endpoint, so the WS message is redundant but misleading.

### Medium Priority

5. **Add TTS preview to settings UI** — Backend has `/api/tts/preview` but no frontend button uses it. Add a "Test Voice" button in voice settings.

6. **Add companion settings to UI** — Backend has full companion settings CRUD but no frontend panel exposes them.

7. **Add settings reset button** — Backend has `/api/settings/reset` but the settings panel has no reset-to-defaults button.

8. **Handle `server_hello`** — Frontend should read platform/capabilities from the response for feature gating.

9. **Clean up dead endpoints** — 42% of REST endpoints are never called. Either expose them in the UI or remove them to reduce attack surface and maintenance burden.

### Low Priority

10. **Normalize MCP config path** — Frontend uses two different paths to save MCP server config (`/api/settings/batch` in mcp.js/mcp-command.js and `/api/mcp/servers` in the backend). Standardize on one.

11. **Add vault/rules UI** — The entire vault system has no frontend; either build the UI or mark these endpoints as internal-only.

12. **Handle `viseme` messages** — Backend sends viseme data but frontend ignores it. Could be used for more precise lip sync.

13. **Push notification client integration** — Push registration endpoints exist but no Capacitor/web frontend calls them. Integrate with Capacitor PushNotifications plugin.
