# Amalgam Architecture & End-to-End Flow Report

**Generated:** 2026-06-22  
**Scope:** Full architecture graph analysis + 5 end-to-end flow traces  
**Methodology:** Static code analysis (import maps, dependency trees, file-size analysis)

---

## AREA 1: Architecture Graph/Map

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                   webui/ (Frontend)                  │
│  app.js ─ orchestrator ─ module/ sub-system          │
│  settings.js  ws.js  voice.js  tts.js  avatar.js     │
│  companion.js  history.js  memory-graph.js  etc.      │
└──────────────────┬──────────────────────────────────┘
                   │ HTTP REST ── /api/*               
                   │ WebSocket ── /ws/chat             
                   ▼
┌─────────────────────────────────────────────────────┐
│                backend/api/ (API Layer)              │
│  app.py (FastAPI factory)                            │
│  ├── api/routes/ (10 route modules)                  │
│  ├── api/ws/handler.py (ChatSession, WS main loop)   │
│  ├── api/ws/tts_service.py (TTS scheduler)           │
│  └── api/deps.py (DI re-export)                      │
└──────────────────┬──────────────────────────────────┘
                   │
┌─────────────────────────────────────────────────────┐
│              backend/core/ (Core Logic)              │
│  deps.py ── singleton registry (global state)        │
│  ├── agent/ (agent types, factory)                   │
│  ├── llm/ (LLMRouter → LiteLLMProvider)              │
│  ├── memory/ (working, episodic, semantic, hybrid)    │
│  ├── config/ (settings, schema)                      │
│  ├── voice/tts/ (TTS router + 14 providers)          │
│  ├── companion/ (scheduler, events)                  │
│  ├── orchestrator/ (plans, blackboard, state)         │
│  ├── mcp/ (MCP client)                               │
│  ├── metacognitive/ (engine, strategy, adaptation)    │
│  ├── self_learning/ (⚠️ built but NOT wired)          │
│  ├── translation/ (DeepLX)                           │
│  └── ...                                              │
└──────────────────┬──────────────────────────────────┘
                   │
┌─────────────────────────────────────────────────────┐
│          backend/voice/ (Voice Pipeline)             │
│  pipeline.py (VoicePipeline + VoiceStateMachine)     │
│  ├── stt/ (STTRouter + 6 providers)                  │
│  ├── wakeword/ (WakeWordRouter)                      │
│  └── vad.py (Voice Activity Detection)               │
└─────────────────────────────────────────────────────┘
```

### 1.2 Python Import Graph (Backend)

**Total imports scanned: 791** unique import statements across **~100 Python files**.

#### Core Dependency Hub: `backend/core/deps.py`
This single module is the **architectural bottleneck** — it owns a global `_shared` dict that lazily initializes ALL major singletons:

```python
_shared = {
    "settings", "llm", "memory", "context_builder", "context_manager",
    "vault", "mcp", "tts", "agent", "relationship", "wakeword",
    "strategy_selector", "orchestrator", "companion",
}
```

Every API route, every WS handler, every core subsystem calls `settings()`, `llm()`, `memory()`, etc. — all of which are thin wrappers around `get_shared()["key"]`. This is a **massive coupling point**: changing any singleton's init sequence affects everything downstream.

#### Import Graph (Simplified)
```
app.py
 ├── api/ws/handler.py ─────┬── api/deps.py ──→ core/deps.py (hub)
 │                          ├── core/translation
 │                          ├── core/orchestrator
 │                          ├── core/paths
 │                          ├── voice/pipeline
 │                          └── api/routes/metrics
 ├── api/routes/* ───────────┬── api/deps.py
 │                          └── core/* (various)
 └── core/startup ───────────┬── core/deps.py
                              └── core/hot_reload
```

### 1.3 Module Dependency Counts (Top Bottlenecks)

Module imports (how many other modules import each module):

| Module | Imported By | Risk |
|--------|------------|------|
| `core/deps.py` (the hub) | **Every module** via api/deps.py | Single point of failure |
| `core/config/settings.py` | ~25+ files | High |
| `core/llm/router.py` | ~15+ files | High |
| `core/memory/manager.py` | ~12+ files | High |
| `core/paths.py` | ~10+ files | Medium |
| `core/agent/base.py` | 5 files (factory + agents) | Medium |

### 1.4 Circular Dependency Detection

**No circular dependencies found** between backend layers:
- `core/` never imports from `api/` (verified: no `backend.api` imports in core)
- `api/routes/*` never import from `api/ws/`
- `api/ws/handler.py` imports exactly one route module: `api/routes/metrics` (for `record_turn`), which is a read-only utility call — no cycle risk

**However**, there's a latent architectural concern: `api/ws/handler.py` imports from both `core/deps` and `api/deps`, creating a dependency chain that includes `api/deps → core/deps`. The reverse (core → api) does not exist, which is healthy.

### 1.5 Dead Code Detection

#### Python Files — Genuinely Never Imported (Dead):

| File | Reason |
|------|--------|
| `backend/core/agent/interface.py` | Abstract interface — never imported anywhere |
| `backend/core/agent/stream_processor.py` | Never imported |
| `backend/core/self_learning/auto_skill.py` | **Built but wired with TODO comments only** |
| `backend/core/self_learning/corrections.py` | **Built but NOT wired** — handler.py has TODO |
| `backend/core/self_learning/preferences.py` | **Built but NOT wired** — handler.py has TODO |
| `backend/core/self_learning/improvement.py` | **Built but NOT wired** |
| `backend/core/skills/curator.py` | Not imported by any active code |
| `backend/core/plugins/example_plugin.py` | Example only |
| `backend/plugins/manager.py` | Plugin manager exists but plugin system is nascent |
| `backend/plugins/emotion_analyzer/plugin.py` | Never activated |
| `backend/cli/companion.py` | Terminal companion — standalone, not imported |
| `backend/cli_stats.py` | Standalone CLI utility |
| `backend/api/telegram.py` | Telegram bot integration — not wired to app |
| `backend/core/permissions.py` | Permissions module exists but not integrated |
| `backend/core/hot_reload.py` | Only partially called in startup |
| `backend/grpc/server.py` | gRPC server — not started by app |
| `backend/core/log_config.py` | Log config file — never executed |

**Note:** The route files (`api/routes/*.py`) appear "never imported" in my raw scan, but they **are** imported indirectly via `from backend.api.routes import (...)` in `app.py`. They are NOT dead code.

#### JS Files — All Are Referenced:

All JS files under `webui/js/` and `webui/js/modules/` are referenced by `app.js` through ES module imports. **No dead JS files.** However, `webui/js/swarm.js` is loaded via `<script>` tag (not ES module), making it a non-module script.

### 1.6 Architectural Bottlenecks

#### 🔴 Critical: Singleton Registry in `core/deps.py`
```python
_shared = { ... }
_init_lock = threading.Lock()
def get_shared(): ...
```
- **Problem**: Global mutable state with thread lock. 14 singletons initialized lazily.
- **Risk**: Race conditions at startup, implicit ordering dependencies, hard to test.
- **Impact**: If any singleton init fails, subsequent calls to `get_shared()` may return partially initialized state.

#### 🔴 Critical: ChatSession is 1200 lines
`backend/api/ws/handler.py` — 1,204 lines in a single class. This is the **largest file** in the project and handles:
- WebSocket message routing (handle_command, handle_slash_command, _handle_plan_command)
- Chat streaming loop (_run_agent_loop)
- Voice input/output management (_voice_input_on/off, _wake_word_on/off)
- TTS orchestration
- Client capability negotiation
- Companion event routing
- MCP config updates

**This should be split into at least 3-4 separate files.**

#### 🟡 High: VoicePipeline is 578 lines + VoiceStateMachine is 210 lines
`backend/voice/pipeline.py` — Contains both the state machine and the pipeline logic in one file.

#### 🟡 High: `backend/core/mcp/client.py` — 609 lines
MCP client is very large and handles too many responsibilities (connection, schema, tool execution, permissions, analytics).

#### 🟡 High: Sync/Async Boundary Issues

1. **`listen_loop()` runs in a thread** (executor), but calls `asyncio.run_coroutine_threadsafe()` to bridge back:
   ```python
   loop.run_in_executor(None, self.voice_pipeline.listen_loop)  # handler.py:523
   asyncio.run_coroutine_threadsafe(self.process_response(text), _main_loop)  # handler.py:494
   ```
   This pattern is fragile — if `_main_loop` is closed or in a different state, the callback silently fails.

2. **`settings().set()` runs in executor** (blocking file I/O):
   ```python
   await loop.run_in_executor(None, lambda: s_obj.set("provider.active", provider_name))
   ```
   This creates latency on every slash command that modifies settings.

3. **Memory `_write_sync` is synchronous** but called via executor: `await loop.run_in_executor(self._executor, self._write_sync, ...)`. This is correct but adds complexity.

#### 🟡 High: Global Variables in JS Modules

Each JS module uses module-level `let` bindings for state:
- `settings.js`: `activeSettingsTab`, `_providerList`, `_charList`, `_vaultFiles`
- `ws.js`: `_reconnectAttempts`, `_reconnectTimer`, `_pingInterval`, `_pongPending`
- `markdown.js`: `_toolCallIdCounter`
- `mcp-command.js`: `_isOpen`, `_selectedIndex`, `_servers`
- `companion.js`: `_idleTimer`, `_isIdle`, `_companionEnabled`

These are safe within ES module scope (not truly global), but they're mutable state that could cause issues with HMR or module re-evaluation.

#### 🟢 Low: Large Files (>500 lines) That Should Be Split

| File | Lines | Recommendation |
|------|-------|---------------|
| `backend/api/ws/handler.py` | 1,204 | **Split ASAP** — ChatSession does too much |
| `webui/js/avatar.js` | 1,465 | VRM avatar rendering — inherently complex, acceptable |
| `webui/js/modules/settings.js` | 1,150 | Split vault/rules/companion into sub-modules |
| `webui/js/app.js` | 1,047 | Main orchestrator — somewhat justified |
| `backend/core/config/models.py` | 954 | Pydantic models — acceptable |
| `backend/core/memory/manager.py` | 826 | Large but focused — consider splitting ChromaDB ops |
| `backend/core/config/settings.py` | 775 | Settings manager — justified |

#### 🟢 Low: Shared Mutable State in Python

- `_in_flight_requests: dict[str, list[float]]` in `app.py` — per-IP rate limiting, properly pruned
- `_LOCAL_EMBEDDING` / `_LOCAL_EMBEDDING_LOADED` in `memory/manager.py` — lazy load, thread-safe via flag
- `_PROVIDER_CLASSES = None` in TTS/STT routers — lazy-loaded class-level cache

---

## AREA 2: End-to-End Flow Verification

### 2.1 Chat Flow

```
User types message in UI
  │
  ▼
app.js: sendBtn or Enter key listener
  │  calls wsInst.send(JSON.stringify({type: "user_message", text, images}))
  │
  ▼
websocket.send (JSON string)
  │  Data format: JavaScript object → JSON.stringify → UTF-8 string
  │
  ▼
handler.py: ChatSession.run() — line 1089
  │  data = await self.ws.receive_json()  ← FastAPI JSON deserialization
  │  msg_type = data.get("type")
  │  ├── "user_message"
  │  └── calls self.process_response(text, images) — line 1113
  │
  ▼
handler.py: ChatSession.process_response() — line 182
  │  await self.cancel_assistant()  # cancel any in-flight response
  │  t = asyncio.create_task(self._run_agent_loop(text, images, this_stream))
  │
  ▼
handler.py: ChatSession._run_agent_loop() — line 190
  │  ├── sends {"type": "chat_start"} ← WS message
  │  ├── sends {"type": "emotion", "emotion": "neutral"}
  │  ├── gets relationship context: relationship().get_context_string(char_id)
  │  ├── enters agent loop:
  │  │   it = agent().handle_user_input(text, images, relationship_context)
  │  │   │  agent() → core/deps.py → AgentFactory → BasicAgent | PlanningAgent | ReflectiveAgent
  │  │   │
  │  │   ▼
  │  │   basic_agent.py: BasicAgent.handle_user_input() — line 124
  │  │     │  Delegates to run() — line 39
  │  │     │  ├── memory.add_turn("user", user_message)
  │  │     │  ├── builds messages via _build_messages()
  │  │     │  ├── gets tool schema via _get_tool_schema()
  │  │     │  ├── calls llm.stream() or llm.stream_with_tools()
  │  │     │  │  │
  │  │     │  │  ▼
  │  │     │  │  llm/router.py: LLMRouter.stream() — line 70
  │  │     │  │    │  Delegates to LiteLLMProvider.stream()
  │  │     │  │    │  │  litellm_provider.py: LiteLLMProvider.stream()
  │  │     │  │    │  │    │  calls litellm.acompletion() ← external
  │  │     │  │    │  │    ▼
  │  │     │  │    │  │  Yields text tokens ← AsyncIterator[str]
  │  │     │  │    │  ▼
  │  │     │  │    │  Yields tokens upward
  │  │     │  │    ▼
  │  │     │  │  Yields: str tokens, dict signals (tool_use)
  │  │     │  ▼
  │  │     │  If tool calls: execute_tool() → MCP client or local tools
  │  │     ▼
  │  │  Yields: str tokens + signal tuples (__emotion__, __thinking__, __tool__, etc.)
  │  │
  │  ├── Iterates async generator:
  │  │   for item → str token → sends {"type": "chat_append", "text": token}
  │  │   for item → tuple → handles emotion/expression/thinking/animation/tool/error signals
  │  │
  │  ├── Sentence-level TTS check (if voice_output_enabled):
  │  │   submits to tts_scheduler.submit(sentence_idx, text, emotion, ws, ...)
  │  │   │  tts_service.py: OrderedTTSScheduler._generate_and_deliver()
  │  │   │    → tts().synthesize() → TTSRouter → specific provider
  │  │   │    → numpy_to_wav_bytes() → base64 encode
  │  │   │    → ws.send_json({"type": "tts_audio", "audio": b64, ...})
  │  │   ▼
  │  │
  │  ├── Post-stream: relationship tracking, translation of full response
  │  ├── Sends {"type": "chat_append", "text": full_response, "finished": True}
  │  └── Records turn metrics via record_turn()
  │
  ▼
websocket.onmessage (WS → frontend)
  │
  ▼
ws.js: connectWS() onmessage handler — line 223
  │  data = JSON.parse(e.data)
  │  handleWSMessage(data)
  │
  ▼
ws.js: handleWSMessage() — line 246
  │  ├── data.type == "chat_start":
  │  │   _addMessage('assistant', '')  ← creates message element
  │  │   setCurrentAssistantMessage(cam)
  │  │   _setStatus('thinking')
  │  │
  │  ├── data.type == "chat_append":
  │  │   let cam = getCurrentAssistantMessage()
  │  │   Strip markers → stream buffer (requestAnimationFrame batched DOM updates)
  │  │   If finished: flush buffer, set status 'ready'
  │  │
  │  ├── data.type == "tts_audio":
  │  │   Push to TTS queue → processTTSQueue()
  │  │
  │  ├── data.type == "emotion" / "expression":
  │  │   avatarRenderer.setEmotion/setExpression()
  │  │
  │  └── data.type == "thinking":
  │      _setStatus('thinking')
  │      avatarRenderer.playNod()
```

#### 🔴 Chat Flow Issues

1. **Race condition: stream_buffer + finished flag**: The stream buffer uses `requestAnimationFrame` for batching. If `finished: true` arrives in the same frame as the last text chunk, the buffer flush order depends on requestAnimationFrame timing.

2. **Error propagation**: If `agent().handle_user_input()` raises an exception that is NOT caught in `_run_agent_loop`, the exception handler on line 362 sends a generic error message to the frontend but does NOT terminate the `stream_idx` check. The frontend may receive `chat_append` with `finished: True` after an error, confusing the UI.

3. **`handle_user_input` returning a coroutine**: Line 207-210 has a defensive check that logs an error if `handle_user_input` returns a coroutine instead of an async generator. This shouldn't happen but the check exists — suggesting this was a real bug at some point.

4. **Translation of full response**: Lines 308-326 translate the full response AFTER streaming. The translated text replaces the original in a final `chat_append` with `finished=True`, but the original streamed content was already displayed. This means the user sees the original language, then it gets replaced — a poor UX.

5. **TTS scheduler not drained on error**: If the agent loop throws (line 353-371), error handling sends error messages but does NOT flush the TTS scheduler. Pending TTS tasks may continue generating and attempt to send audio after an error state.

### 2.2 Voice Flow

```
User speaks into microphone
  │
  ├── Route A: Browser STT
  │   voice.js: startBrowserSpeechRec()
  │     │  Uses Web Speech API (SpeechRecognition)
  │     │  onresult event: gets final transcript
  │     │  ws.send({type: "user_message", text: finalText})
  │     ▼
  │   (continues to standard chat flow)
  │
  └── Route B: Server-side STT
      handler.py: ChatSession._voice_input_on() — line 482
        │  Creates VoicePipeline with STT provider
        │  VoicePipeline configured via configure_stt_pipeline()
        │  voice_task = loop.run_in_executor(None, self.voice_pipeline.listen_loop)
        │
        ▼
      pipeline.py: VoicePipeline.listen_loop() — line 348
        │  Runs in thread executor (blocking I/O)
        │  sounddevice.RawInputStream → audio frames
        │  VAD (Voice Activity Detection) → detects speech
        │  Buffers audio → silence timeout → submits to STT
        │
        ├── VAD detects speech → _on_speech_start callback
        │     → asyncio.run_coroutine_threadsafe(cancel_assistant(), _main_loop)
        │     → interrupts current assistant response
        │
        ├── Silence detected → VoiceState.PROCESSING
        │     → _submit_stt_with_timeout(audio_data)
        │     → _stt_executor.submit(self._stt.transcribe, audio_data)
        │     │  STTRouter.transcribe() → specific provider:
        │     │    faster-whisper, openai-whisper, groq-whisper,
        │     │    whispercpp, or deepgram
        │     ▼
        → future.add_done_callback(_on_stt_done)
        │  → agent_callback(text)
        │  → asyncio.run_coroutine_threadsafe(self.process_response(text), _main_loop)
        │  → asyncio.run_coroutine_threadsafe(self.send({type: "user_message_from_voice"}), _main_loop)
        ▼
      (continues to standard chat flow)
        │
        ▼
      TTS path (for voice output):
      handler.py: _run_agent_loop() → sentence-level TTS
        │
        ▼
      tts_service.py: OrderedTTSScheduler
        │  submit(idx, text, emotion, ws, stream_id, stream_ref)
        │  → _generate_and_deliver() → asyncio.create_task
        │    → _do_generate()
        │      → tts().synthesize(text, ref_audio, emotion)
        │        │  TTSRouter → specific provider (edge-tts, elevenlabs, etc.)
        │        ▼
        → numpy float32 audio + sample rate + optional visemes
        → numpy_to_wav_bytes() → base64 encode
        → ws.send_json({"type": "tts_audio", "audio": b64, ...})
        │
        ▼
      ws.js: handleWSMessage()
        │  data.type == "tts_audio"
        │  → push to TTS queue
        │  → processTTSQueue() → plays audio via Audio element
        │  → viseme_schedule → avatar lipsync
```

#### 🔴 Voice Flow Issues

1. **Thread safety of `_main_loop`**: `listen_loop()` captues `asyncio.get_running_loop()` on line 363, but it's called from `run_in_executor` (a thread). In Python 3.10+, `get_running_loop()` raises `RuntimeError` if no running loop in the current thread. The try/except on line 363-365 catches this silently, setting `_main_loop = None`. If `_main_loop` is None, `asyncio.run_coroutine_threadsafe()` on line 494 will raise `RuntimeError("There is no current event loop in thread '...'")`.

2. **STT watchdog timer creates new threads**: Line 338 creates `threading.Timer` for each STT submission. If STT is fast, these are cancelled, but rapid speech detection could create thread churn.

3. **Browser STT race with server-side STT**: The `stt_engine == "browser"` check on line 483 is checked at voice_input_on time. If the user changes the STT engine while voice input is active, the behavior is undefined — the browser STT callback on `voice.js` line 72 sends `user_message` directly to WS, while the server-side pipeline also sends `user_message_from_voice`. This could cause **duplicate messages**.

4. **Barge-in cancellation gap**: `on_speech_start` → `cancel_assistant()` cancels the current task, but `cancel_assistant()` sets `stream_idx += 1` on line 179. The `_run_agent_loop` checks `this_stream != self.stream_idx` on line 213. However, the TTS scheduler tasks are NOT immediately cancelled — they check `stream_ref() != stream_id` which is the same check. There's a window where a TTS sentence could be in the middle of generation when the cancel happens.

5. **No error recovery for listen_loop crashes**: If `listen_loop()` crashes (line 506-508), the exception is logged but the `VoicePipeline` is left in an unknown state. The `ChatSession` doesn't detect this — it only checks `self.voice_task.done()` on line 520.

### 2.3 Companion Flow

```
Frontend:
  companion.js — Idle detection (client-side)
    │  Listens for mousedown, keydown, touchstart, scroll, mousemove
    │  On idle timeout (default 5 min):
    │    ws.send({type: "idle_enter"})
    │  On activity resumption:
    │    ws.send({type: "idle_exit"})
    │
    ▼
  handler.py: ChatSession.run() — message loop
    │  type == "idle_enter" (line 1139):
    │    → companion().on_event(CompanionEvent(IDLE_ENTER))
    │  type == "idle_exit" (line 1149):
    │    → asyncio.create_task(companion().on_event(CompanionEvent(IDLE_EXIT)))
    │
    ▼
  companion/scheduler.py: CompanionScheduler
    │  on_event() — line 105:
    │    IDLE_ENTER → sets idle state, starts idle timer
    │    IDLE_EXIT → clears idle state → _on_welcome_back()
    │
    ├── Background loop (_loop()) — runs every 30 seconds:
    │   ├── Check idle timeouts: if idle > idle_check_delay → _on_idle_check_in()
    │   └── Time-awareness: if hour changed → _on_time_change()
    │
    ├── _generate_and_send() — line 283:
    │   ├── _build_companion_prompt() → LLM system + user messages
    │   ├── _generate_companion_text() → self._llm().generate(messages)
    │   │  Uses LLMRouter.generate() — non-streaming
    │   └── send_fn(payload) → ws.send_json({"type": "companion", "content": text, "context": ...})
    │
    ▼
  ws.js: handleWSMessage()
    │  data.type == "companion"
    │  → _addMessage('assistant', data.content)
    │  → cam.classList.add('msg-companion')
    │  → _setStatus('ready')
```

#### 🔴 Companion Flow Issues

1. **Fire-and-forget tasks**: `_on_idle_check_in`, `_on_welcome_back` (line 1154-1158), and `_on_time_change` are scheduled with `asyncio.create_task()` but their results are never awaited or collected. If they fail, the error is silently logged.

2. **Client-side idle detection is unreliable**: JavaScript's `mousemove` event fires even when the user is reading (passive). The companion module doesn't debounce effectively. Idle detection should use the `IdleManager` class in `idle-manager.js` (which exists!) but the companion module seems to implement its own.

3. **LLM call per idle check**: Every idle check-in generates an LLM call. If the user idles frequently, this burns tokens. The scheduler has no rate-limiting beyond the idle check delay setting.

4. **No companion mode on fresh reload**: If `_companionEnabled` (companion.js line 14) defaults to false, the idle listeners might not be registered until settings are loaded from the server.

5. **Missing companion route handler for `idle_prompt_request`**: On line 1098, `idle_prompt_request` uses `agent().generate_idle_prompt()` instead of the CompanionScheduler, creating a separate idle prompt path that doesn't use companion settings.

### 2.4 Settings Flow

```
UI: User changes a field in settings panel
  │
  ▼
settings.js: renderField() → generates HTML with onchange/listeners
  │  Field change → delegate event handler (line 1014)
  │  OR Save button click → saveCategory(category)
  │
  ▼
settings.js: saveCategory() — line 424
  │  Collect all field values in category
  │  Build changed dict: {key: value}
  │
  ├── POST /api/settings/batch
  │   body: JSON.stringify({settings: changed})
  │   │  Data format: JS object → JSON string → HTTP POST
  │   │
  │   ▼
  │   api/routes/settings.py: batch_set_settings() — line 241
  │     │  body = BatchSettingsRequest(settings=dict)
  │     │  _validate_settings_update(pairs) — validates all values
  │     │  s = settings()
  │     │  for key, value: s.set(key, value)
  │     │  llm().reload_settings()
  │     │  agent().update_settings(s)
  │     │
  │     ├── settings() → core/deps.py → Settings() singleton
  │     │   s.set(key, value) → updates in-memory dict + triggers file write
  │     │   │  core/config/settings.py: Settings.set()
  │     │   │  → sets self._data[key] = value
  │     │   │  → self._save() — writes JSON to data/settings/profiles/*.json
  │     │   ▼
  │     │  Returns {"status": "ok"}
  │     │
  │     ▼
  │   Response: JSON
  │
  ├── On success: showToast + refresh settings
  │   const s = await api('/api/settings')
  │   setSettingsCache(s)
  │
  ├── Companion fields saved separately via companion API
  │   POST /api/companion/settings
  │
  └── Global: _attachSettingsDelegates() — change event listener
        Fields that trigger immediate effects:
          theme → applyTheme()
          language → POST /api/settings/set (no reload)
          accent_color → applyAccentColor()
          font_size → CSS variable update
          stt_engine/tts_engine/active_provider → re-render category
          voice_input/voice_output → header toggle state
```

#### 🔴 Settings Flow Issues

1. **Double save for companion settings**: `saveCategory('Character')` saves `companion.*` keys via `/api/settings/batch`, then immediately saves them again via `_saveCompanionSettings()` → `POST /api/companion/settings`. This is **redundant** — the companion settings route writes to the same settings singleton.

2. **Settings not propagated to running subsystems**: After `batch_set_settings()`, only `llm.reload_settings()` and `agent().update_settings()` are called. But TTS provider changes, STT engine changes, and wake word changes require reconfiguration that isn't triggered. The voice pipeline must be manually restarted.

3. **Validation mismatch**: The frontend uses `SETTINGS_SCHEMA` (in `settings-schema.js`) for field rendering, while the backend validates in `_validate_settings_update()`. If the schemas drift, the backend may reject values the frontend allows.

4. **No settings diff**: `saveCategory()` sends ALL fields in a category, even unchanged ones. For large categories like "Provider" (which may include many API keys), this is wasteful and risks sending stale values.

5. **Frontend settings cache vs. backend race**: `setSettingsCache(s)` on line 471 sets the client-side settings. But between the save request completing and the refresh GET request, another browser tab could have changed settings. The cache is stale.

### 2.5 Memory Flow

```
User sends a message
  │
  ▼
basic_agent.py: run() — line 39
  │  await self.memory.add_turn("user", user_message)  — line 44
  │
  ▼
memory/manager.py: Memory.add_turn() — line 363
  │  session_id = self.get_current_session()
  │
  ├── 1. Working memory: self._working.add(role, content)
  │     In-memory buffer of last 20 turns (always active)
  │
  ├── 2. If memory disabled: return early
  │
  ├── 3. Get embedding: _get_embedding(content)
  │     ├── Check FACT cache → return cached
  │     ├── If backend == "local": SentenceTransformer("all-MiniLM-L6-v2")
  │     └── If backend == "provider": llm.get_embedding()
  │
  ├── 4. Write to disk: _write_sync(session_id, data)
  │     → JSON file in CONVERSATIONS_DIR (2025/06/22/103045.json)
  │     → Thread pool executor (async wrapper around sync write)
  │
  ├── 5. Update session index → SessionIndex.upsert()
  │
  ├── 6. If embedding exists: ChromaDB add
  │     (vector store for semantic search)
  │
  ├── 7. Background summarization: _safe_summarize() → check_and_summarize()
  │     If message count > threshold (40):
  │       → llm.generate() with compaction prompt
  │       → Replace old messages with summary
  │
  ├── 8. FTS5 index: _fts.index_message()
  │
  └── 9. Episodic memory: _get_episodic(session_id).add_episode()
      │  Per-session ChromaDB collection for recall
      │
      ▼
Memory retrieval (for context building):
  memory/manager.py: get_relevant(query) — line 604
    │  retrieve_for_context(query, session_id, n=N)
    │  ├── Check FACT cache (instant)
    │  ├── RRF hybrid: BM25 + ChromaDB
    │  └── Cache result for 5 minutes
    │
    ▼
  Routes:
    GET /api/memory/sessions → get_sessions()
    GET /api/memory/session/{id} → get_session_messages()
    GET /api/memory/search?q=... → search_all_sessions() or get_relevant()
    POST /api/memory/clear → clear()
    DELETE /api/memory/session/{id} → delete_session()
```

#### 🔴 Memory Flow Issues

1. **Synchronous file I/O in thread pool**: `_write_sync()` (line 194) is synchronous blocking I/O called via executor. For each message turn, this means:
   - JSON serialization of entire session data
   - File write of full session JSON
   - ChromaDB add (if embedding exists)
   - FTS5 index write
   - Session index write
   **This is ~5 I/O operations per message turn.** For a fast conversation, this could create backpressure.

2. **ChromaDB as singleton dependency**: `chromadb.PersistentClient` is created once at Memory init. If ChromaDB crashes or the collection is corrupted, the entire memory subsystem degrades gracefully (lines 64-82) but silently loses vector search capability.

3. **Embedding fallback chain is fragile**: `_get_embedding()` (line 270) tries backend → provider → local → None. Each fallback is wrapped in try/except with `logger.debug`. Failures at each level are silent, potentially returning None embedding and silently disabling vector search.

4. **Summarization runs on every turn**: `add_turn()` calls `asyncio.create_task(self._safe_summarize())` on line 427. The `_summarize_lock` prevents concurrent summarizations, but the task is created for every single message, even if the count is below threshold.

5. **No per-session embedding enforcement**: When `memory.enabled = False` (line 96-100), memory skips disk writes but still adds to working memory. However, context builders (`context_builder.py`) use `get_recent()` which includes working memory — but the settings toggle only controls disk persistence, not context injection.

6. **Memory graph only visualizes, doesn't integrate**: The `memory-graph.js` module renders a canvas-based graph visualization using ChromaDB data, but it's purely visual. The graph is not used for retrieval or context reordering.

---

## Summary of Critical Findings

### 🔴 Critical (Must Fix)

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| 1 | ChatSession 1200 lines | `backend/api/ws/handler.py` | Maintainability, testability |
| 2 | Global singleton hub | `backend/core/deps.py` | Startup races, test isolation |
| 3 | `_main_loop` may be None in voice thread | `backend/voice/pipeline.py:363` | Voice crashes silently |
| 4 | Self-learning modules built but not wired | `backend/core/self_learning/*` | 4 modules = dead code |
| 5 | TTS scheduler not drained on agent error | `backend/api/ws/handler.py:353` | Ghost TTS after error |

### 🟡 High Priority

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| 6 | Duplicate companion settings save | `settings.js:474-510` | 2x API calls |
| 7 | Browser/Server STT duplicate messages | `voice.js:72` + `handler.py:482-524` | Double processing |
| 8 | Translation replaces already-streamed text | `handler.py:308-326` | UX: text changes mid-display |
| 9 | ~5 I/O ops per message turn | `memory/manager.py:363-436` | Latency on fast conversations |
| 10 | Settings not propagated to all subsystems | `settings.py:254-261` | Stale runtime config |

### 🟢 Watch Items

| # | Issue | Location |
|---|-------|----------|
| 11 | `_LOCAL_EMBEDDING` global cache | `memory/manager.py:32` |
| 12 | JS module-level mutable state | All `webui/js/modules/*.js` |
| 13 | No gRPC server startup | `backend/grpc/server.py` |
| 14 | `__init__.py` empty in `api/routes/` | `backend/api/routes/__init__.py` |
| 15 | `hot_reload.py` partially wired | `backend/app.py:258-262` |

---

## Architecture Graph

Graphify was attempted but requires an API key. Manual analysis complete.

**Key architectural patterns:**
- **DI via global singleton registry** (core/deps.py) — functional, but not ideal for testability
- **Layered architecture**: webui → api → core (no reverse dependencies from core → api)
- **Plugin system**: nascent, with `plugin.py` registry but few actual plugins
- **Dynamic provider loading**: TTS and STT use lazy-loaded `_PROVIDER_CLASSES` to avoid importing all providers at startup
- **Component-based frontend**: ES modules with `app.js` as orchestrator, `state.js` for shared state
