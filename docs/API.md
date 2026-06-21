# Amalgam API Reference

Complete reference for all REST endpoints and WebSocket messages.

## Table of Contents

- [Base URL](#base-url)
- [Health & Readiness](#health--readiness)
- [Settings](#settings)
- [Characters](#characters)
- [Voice](#voice)
- [Memory & Sessions](#memory--sessions)
- [MCP Tools](#mcp-tools)
- [Vault](#vault)
- [Relationship](#relationship)
- [Metrics](#metrics)
- [Companion](#companion)
- [Setup Wizard](#setup-wizard)
- [Push Notifications](#push-notifications)
- [WebSocket Protocol](#websocket-protocol)
- [Error Codes](#error-codes)
- [Slash Commands](#slash-commands)

---

## Base URL

```
http://localhost:8000
```

All endpoints are prefixed with `/api/` except health checks and static asset serving.

---

## Health & Readiness

### `GET /api/health`

Service health status. Returns cached states (instant).

**Response:**
```json
{
  "status": "ok",
  "service": "amalgam",
  "version": "0.1.0",
  "uptime": 123.45,
  "services": {
    "llm": { "status": "ok", "latency_ms": 45.2 },
    "tts": { "status": "ok", "latency_ms": 12.1 },
    "memory": { "status": "ok" }
  }
}
```

### `GET /ready`

Readiness probe. Checks database connectivity.

**Response (200):**
```json
{ "status": "ok", "database": true }
```

**Response (503):**
```json
{ "status": "degraded", "database": false }
```

---

## Settings

### `GET /api/settings`

Get all settings.

**Response:**
```json
{
  "provider": { "active": "gemini", "gemini": { "model": "gemini-2.0-flash", "api_key": "AIzaSy..." } },
  "voice": { "engine": "edge-tts", "stt_engine": "browser" },
  "character": { "active": "default" },
  "ui": { "theme": "dark", "language": "en" }
}
```

### `POST /api/settings`

Update settings (bulk). Body is a flat or nested dict of key-value pairs.

**Request:**
```json
{
  "provider": { "active": "claude" },
  "voice": { "engine": "elevenlabs" },
  "ui": { "theme": "midnight" }
}
```

**Response:**
```json
{ "status": "ok", "voice": "elevenlabs" }
```

**Error Response:**
```json
{ "status": "error", "errors": ["Unknown provider: foo"], "voice": "edge-tts" }
```

### `POST /api/settings/set`

Set a single setting by dot-notation key.

**Request:**
```json
{ "key": "voice.engine", "value": "edge-tts" }
```

**Response:**
```json
{ "status": "ok" }
```

### `POST /api/settings/batch`

Set multiple settings at once.

**Request:**
```json
{
  "settings": {
    "voice.engine": "edge-tts",
    "provider.active": "ollama"
  }
}
```

**Response:**
```json
{ "status": "ok", "count": 2 }
```

### `GET /api/settings/get/{key:path}`

Get a single setting value by dot-notation key.

**Example:** `GET /api/settings/get/voice.engine`

**Response:**
```json
{ "key": "voice.engine", "value": "edge-tts" }
```

### `POST /api/settings/test/{provider}`

Test connection to a provider. Provider-specific: may require API key in settings.

**Response:**
```json
{
  "ok": true,
  "latency_ms": 234.5,
  "error": ""
}
```

---

## Characters

### `GET /api/characters`

Return all available characters with their full definitions.

**Response:**
```json
{
  "default": {
    "name": "Default",
    "voice": "en-US-AriaNeural",
    "personality": "friendly, helpful",
    "_dir": "/path/to/characters/default"
  }
}
```

### `GET /api/characters/{character_id}`

Get a specific character's definition.

**Response (200):**
```json
{
  "name": "My Character",
  "voice": "en-US-GuyNeural",
  "personality": "witty, playful",
  "system_prompt": "You are..."
}
```

**Response (404):**
```json
{ "error": "Character not found" }
```

### `GET /api/animations?char_id={id}`

Return available VRMA animation files.

**Response:**
```json
{
  "default": [
    { "file": "wave.vrma", "name": "wave", "url": "/characters/default/anim/wave.vrma" }
  ],
  "character": [
    { "file": "dance.vrma", "name": "dance", "url": "/characters/mychar/anim/dance.vrma" }
  ]
}
```

### `GET /api/emotions`

Return supported TTS emotions.

**Response:**
```json
{ "emotions": ["neutral", "happy", "sad", "angry", "surprised"] }
```

### `GET /api/expressions?char_id={id}`

Return VRM expression presets.

**Response:**
```json
{ "expressions": ["neutral", "happy", "sad", "angry", "relaxed", "surprised"] }
```

### `GET /api/voices`

Return available TTS voices.

**Response:**
```json
[
  { "id": "en-US-AriaNeural", "name": "Aria", "language": "en-US", "gender": "Female" },
  { "id": "en-US-GuyNeural", "name": "Guy", "language": "en-US", "gender": "Male" }
]
```

### `GET /api/models/{provider}`

Fetch available models for a provider.

**Supported providers:** ollama, gemini, opencode, claude, aws, gcp, and all OpenAI-compatible providers.

**Response:**
```json
{ "models": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"] }
```

### `POST /api/icons/regenerate`

Regenerate character icons (VRM renderer + letter fallback).

**Response:**
```json
{ "status": "ok", "method": "vrm+letter", "count": 2, "details": "..." }
```

---

## Voice

### `POST /api/tts/preview`

Preview TTS synthesis. Returns base64-encoded WAV audio.

**Request:**
```json
{ "text": "Hello, I am your assistant." }
```

**Response:**
```json
{
  "audio": "UklGRi...",
  "format": "wav"
}
```

**Error Response:**
```json
{ "audio": null, "error": "TTS synthesis timed out. Try a shorter text." }
```

---

## Memory & Sessions

### `GET /api/memory/sessions`

List all conversation sessions.

**Response:**
```json
{
  "sessions": [
    { "id": "session-abc123", "title": "Chat about cooking", "message_count": 24, "created_at": 1700000000 }
  ],
  "current": "session-abc123"
}
```

### `GET /api/memory/session/{session_id}`

Get messages for a session. Use `"current"` as session_id to get the active session.

**Response:**
```json
{
  "messages": [
    { "role": "user", "content": "Hello!" },
    { "role": "assistant", "content": "Hi! How can I help you?" }
  ],
  "session_id": "session-abc123",
  "exists": true
}
```

### `GET /api/memory/session/{session_id}/resume`

Get the last N turns of a session.

**Query params:** `turns` (default: 5)

**Response:**
```json
{
  "messages": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

### `POST /api/memory/session/{session_id}/activate`

Switch the active session to an existing one.

**Response:**
```json
{
  "session_id": "session-abc123",
  "messages": [...],
  "status": "ok"
}
```

### `POST /api/memory/session/{session_id}/rename`

Rename a session.

**Request body (form):** `new_title=My Chat`

**Response:**
```json
{ "status": "ok", "title": "My Chat" }
```

### `DELETE /api/memory/session/{session_id}`

Delete a session.

**Response:**
```json
{ "status": "ok" }
```

### `POST /api/memory/new-session`

Create a new conversation session.

**Response:**
```json
{ "session_id": "session-xyz789", "status": "ok" }
```

### `POST /api/memory/clear`

Clear all memory and start fresh.

**Response:**
```json
{ "status": "ok" }
```

### `GET /api/memory/session/current`

Get the current session's messages.

**Response:**
```json
{
  "session_id": "session-abc123",
  "messages": [...]
}
```

### `GET /api/memory/search?q={query}&scope={session|all}`

Semantic search across conversation history.

- `scope=session` - Search within current session only
- `scope=all` - Search across all sessions

**Response:**
```json
{
  "results": [
    { "content": "...", "score": 0.85, "session_id": "session-abc123" }
  ]
}
```

---

## MCP Tools

### `GET /api/mcp/servers`

Get configured MCP servers and their connection status.

**Response:**
```json
{
  "servers": [
    {
      "name": "shell",
      "command": "python",
      "args": ["-m", "backend.mcp.servers.shell"],
      "enabled": true,
      "connected": true
    }
  ]
}
```

### `POST /api/mcp/servers`

Update MCP server configuration. **Requires restart to apply changes.**

**Request:**
```json
{
  "servers": [
    { "name": "shell", "command": "python", "args": ["-m", "backend.mcp.servers.shell"], "enabled": true }
  ]
}
```

**Response:**
```json
{ "status": "ok", "message": "MCP settings saved. Restart to apply changes." }
```

### `GET /api/mcp/tools`

Get all available MCP tools.

**Response:**
```json
{
  "tools": [
    {
      "name": "run_shell_command",
      "description": "Execute a shell command",
      "inputSchema": { "type": "object", "properties": { "command": { "type": "string" } } },
      "server": "shell"
    }
  ]
}
```

### `POST /api/shell/approve`

Approve a previously blocked shell command.

**Request:**
```json
{ "cmd": "rm -rf /tmp/test", "mode": "once" }
```

- `mode`: `"once"` | `"prefix"` | `"exact"`

**Response:**
```json
{ "status": "ok", "mode": "once", "cmd": "rm -rf /tmp/test" }
```

---

## Vault

### `GET /api/rules`

Get the current rules (rules.md) content.

**Response:**
```json
{ "content": "Always be polite. Use markdown formatting." }
```

### `POST /api/rules`

Save rules content.

**Request:**
```json
{ "content": "Always be polite. Use markdown formatting." }
```

**Response:**
```json
{ "status": "ok" }
```

### `GET /api/vault/files`

List all vault files.

**Response:**
```json
{ "files": ["notes.md", "recipes.md", "rules.md"] }
```

### `GET /api/vault/files/{filename}`

Read a vault file.

**Response:**
```json
{ "name": "notes.md", "content": "# My Notes\n\n..." }
```

### `POST /api/vault/files/{filename}`

Write/create a vault file.

**Request:**
```json
{ "content": "# Updated Notes\n\n..." }
```

**Response:**
```json
{ "status": "ok" }
```

### `DELETE /api/vault/files/{filename}`

Delete a vault file.

**Response:**
```json
{ "status": "ok" }
```

### `GET /api/vault/search?q={query}&mode={keyword|semantic}&max_results={n}`

Search vault files.

- `mode=keyword` - Fast text matching (default)
- `mode=semantic` - ChromaDB embedding-based search

**Response:**
```json
{
  "results": [
    { "name": "notes.md", "content": "...", "score": 0.9 }
  ],
  "mode": "keyword"
}
```

---

## Relationship

### `GET /api/relationship/{character_id}`

Get relationship stats with a character.

**Response:**
```json
{
  "character_id": "default",
  "sentiment": 0.72,
  "stage": "friend",
  "interactions": 42,
  "trust": 0.65
}
```

---

## Metrics

### `GET /api/metrics/turns?limit={n}`

Get recent conversation turns with token/cost data.

**Response:**
```json
{
  "turns": [
    {
      "timestamp": 1700000000,
      "token_in": 150,
      "token_out": 200,
      "token_total": 350,
      "latency_ms": 1234.5,
      "cost": 0.00045,
      "model": "gemini-2.0-flash",
      "tools_used": 2,
      "errors": 0
    }
  ]
}
```

### `GET /api/metrics/tool-stats?tool={name}`

Get aggregated tool analytics. Optionally filter by tool name.

**Response:**
```json
{
  "total_calls": 45,
  "total_failures": 2,
  "tools": {
    "run_shell_command": {
      "calls": 20,
      "success_rate": 95.0,
      "avg_latency_ms": 120.5
    }
  }
}
```

### `GET /api/metrics/tool-history?limit={n}`

Get recent tool call history.

**Response:**
```json
{
  "history": [
    {
      "tool": "run_shell_command",
      "success": true,
      "latency_ms": 89.3,
      "timestamp": 1700000000
    }
  ]
}
```

### `GET /api/metrics/summary`

Get aggregate summary of all metrics.

**Response:**
```json
{
  "total_turns": 120,
  "total_cost": 0.0543,
  "total_tokens": 45000,
  "avg_latency_ms": 1150.2,
  "tool_calls": 45,
  "tool_failures": 2
}
```

---

## Companion

### `GET /api/companion/settings`

Get companion mode settings.

**Response:**
```json
{
  "enabled": false,
  "idle_check_delay": 10,
  "proactive_interval": 60,
  "time_awareness": true,
  "personality_notes": ""
}
```

### `POST /api/companion/settings`

Update companion settings.

**Request:**
```json
{
  "enabled": true,
  "idle_check_delay": 15,
  "proactive_interval": 120
}
```

**Response:**
```json
{ "ok": true, "settings": { ... } }
```

### `POST /api/companion/trigger`

Manually trigger a companion message.

**Response (success):**
```json
{ "ok": true, "content": "Hey, I was thinking about our conversation earlier..." }
```

**Response (failure):**
```json
{ "ok": false, "error": "Companion scheduler not initialized" }
```

---

## Setup Wizard

### `GET /api/setup/status`

Check if first-time setup is needed.

**Response:**
```json
{
  "needs_setup": true,
  "completed_steps": [],
  "providers": [
    { "id": "openai", "name": "OpenAI (ChatGPT)", "has_free_tier": false, "needs_api_key": true, "default_model": "gpt-4o-mini" }
  ]
}
```

### `GET /api/providers`

Get available providers with models and defaults.

**Response:**
```json
[
  {
    "id": "openai",
    "name": "OpenAI (ChatGPT)",
    "has_free_tier": false,
    "needs_api_key": true,
    "default_model": "gpt-4o-mini",
    "models": ["gpt-4o-mini", "gpt-4o"],
    "api_key_hint": "starts with sk- or sk-proj- (51+ chars)"
  }
]
```

### `POST /api/setup/step1`

Configure provider + test connection.

### `POST /api/setup/step2`

Configure voice (STT engine + TTS engine + test).

### `POST /api/setup/step3`

Configure character + behavior preferences.

---

## Push Notifications

### `POST /api/push/register`

Register a push notification token (Capacitor native shell).

**Request:**
```json
{ "token": "device-push-token-abc", "platform": "ios", "device_id": "device-123" }
```

**Response:**
```json
{ "status": "ok" }
```

### `POST /api/push/unregister`

Unregister a push notification token.

**Request:**
```json
{ "token": "device-push-token-abc" }
```

**Response:**
```json
{ "status": "ok" }
```

---

## WebSocket Protocol

Connect to: `ws://localhost:8000/ws/chat`

All messages are JSON objects with a `type` field.

### Client -> Server Messages

#### Chat Message

```json
{ "type": "chat", "text": "Hello, how are you?", "images": [] }
```

- `text` - User message text
- `images` - Optional array of base64-encoded image strings

#### Voice Commands

```json
{ "type": "command", "cmd": "voice_output_on" }
{ "type": "command", "cmd": "voice_output_off" }
{ "type": "command", "cmd": "voice_input_on" }
{ "type": "command", "cmd": "voice_input_off" }
{ "type": "command", "cmd": "wake_word_on" }
{ "type": "command", "cmd": "wake_word_off" }
```

#### Avatar Commands

```json
{ "type": "command", "cmd": "set_expression", "data": { "expression": "happy" } }
{ "type": "command", "cmd": "set_emotion", "data": { "emotion": "sad" } }
{ "type": "command", "cmd": "play_animation", "data": { "animation": "wave" } }
```

#### Cancel Current Response

```json
{ "type": "cancel" }
```

#### Permission Response

```json
{ "type": "permission_response", "approved": true, "command": "rm -rf /tmp/test" }
```

#### Slash Commands

Sent as regular chat messages starting with `/`:

```json
{ "type": "chat", "text": "/help" }
{ "type": "chat", "text": "/provider claude" }
{ "type": "chat", "text": "/theme midnight" }
```

#### Ping (heartbeat)

```json
{ "type": "ping" }
```

### Server -> Client Messages

#### Chat Text (streaming)

```json
{ "type": "chat_append", "role": "assistant", "text": "Hello!", "finished": false }
{ "type": "chat_append", "role": "assistant", "text": "", "finished": true }
```

- `finished: true` indicates end of response
- `error: true` indicates an error message
- `role: "system"` for system messages (slash command results, errors)

#### Chat Start

```json
{ "type": "chat_start", "role": "assistant" }
```

#### Emotion

```json
{ "type": "emotion", "emotion": "happy" }
```

Emotions: `neutral`, `happy`, `sad`, `angry`, `surprised`, `fearful`, `disgusted`

#### Expression

```json
{ "type": "expression", "expression": "happy" }
```

VRM expression presets: `neutral`, `happy`, `sad`, `angry`, `relaxed`, `surprised`

#### Thinking

```json
{ "type": "thinking", "text": "Let me consider that..." }
```

#### Animation

```json
{ "type": "animation", "name": "wave", "url": "/characters/default/anim/wave.vrma" }
```

#### Tool Call

```json
{ "type": "tool_call", "text": "Running shell command: ls -la" }
```

#### Roleplay

```json
{ "type": "roleplay", "text": "smiles warmly", "animation_url": "/characters/default/anim/smile.vrma" }
```

#### Viseme (lip-sync)

```json
{ "type": "viseme", "value": 0.7 }
```

- `value` is a float 0.0 (closed) to 1.0 (wide open)

#### Voice State

```json
{ "type": "voice_state", "state": "speaking" }
{ "type": "voice_state", "state": "recording" }
{ "type": "voice_state", "state": "idle" }
```

#### Voice Audio (TTS)

```json
{ "type": "voice_audio", "audio": "<base64-wav>", "format": "wav", "sentence_idx": 0 }
```

#### TTS Interrupt

```json
{ "type": "tts_interrupt" }
```

#### Permission Request

```json
{ "type": "permission_request", "command": "rm -rf /tmp/test" }
```

Client must respond with a `permission_response` message.

#### Theme Change

```json
{ "type": "theme_change", "theme": "midnight" }
```

#### Wake Word State

```json
{ "type": "wake_word_state", "enabled": true }
{ "type": "wake_word_state", "enabled": false, "error": "Failed to start" }
```

#### Visibility

```json
{ "type": "visibility", "visible": true }
```

#### Error

```json
{
  "type": "error",
  "service": "agent",
  "message": "Rate limit exceeded",
  "recoverable": true,
  "suggestion": "Try again in 30 seconds",
  "details": {}
}
```

#### Session ID

```json
{ "type": "session_id", "session_id": "session-abc123" }
```

---

## Error Codes

| HTTP Code | Description |
|---|---|
| 200 | Success |
| 400 | Bad request / validation error |
| 404 | Resource not found |
| 422 | Request validation failed (Pydantic) |
| 429 | Rate limit exceeded |
| 500 | Internal server error |

**Rate Limiting:** 120 requests per minute per IP. Health check endpoints (`/api/health`, `/ready`) are exempt.

**Validation Errors (422):**
```json
{
  "error": "Validation failed",
  "details": [
    { "field": "body → key", "message": "Field required" }
  ]
}
```

---

## Slash Commands

These can be sent as chat messages (prefixed with `/`) or used via the REST API:

| Command | Description | Example |
|---|---|---|
| `/clear` | Clear history and start fresh | `/clear` |
| `/new` | Start a new session | `/new` |
| `/resume` | Show last 5 turns | `/resume` |
| `/rename <title>` | Rename current session | `/rename Cooking Chat` |
| `/status` | Show provider, model, session | `/status` |
| `/compact` | Force memory compaction | `/compact` |
| `/help` | Show available commands | `/help` |
| `/provider <name>` | Switch AI provider | `/provider claude` |
| `/model <name>` | Switch model | `/model gpt-4o` |
| `/settings [key] [val]` | Show or set config | `/settings voice.engine edge-tts` |
| `/memory` | Show memory stats | `/memory` |
| `/stats` | Show tool usage analytics | `/stats` |
| `/health` | Run live health checks | `/health` |
| `/theme <name>` | Switch UI theme | `/theme midnight` |
| `/character <name>` | Load a character | `/character alice` |
| `/profile <name>` | Switch settings profile | `/profile quality` |
| `/think` | Toggle thinking display | `/think` |
| `/companion` | Toggle companion mode | `/companion` |
| `/permission <level>` | Set permission level | `/permission readonly` |
