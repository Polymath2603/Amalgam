# Codebase Architecture

## Directory Tree
```
/home/leonardo/Workplace/k/
├── backend/
│   ├── __main__.py              # Entry point, starts uvicorn
│   ├── app.py                   # FastAPI app factory, lifespan, mount static/media
│   ├── paths.py                 # PROJECT_ROOT, DATA_DIR, CHARS_DIR — single source of truth
│   ├── api/
│   │   ├── deps.py              # Depends() — shared component injection
│   │   ├── ws/
│   │   │   ├── handler.py       # WebSocket chat handler (extracted from old server.py)
│   │   │   └── tts_service.py   # TTS synthesis + sentence streaming + stream invalidation
│   │   └── routes/
│   │       ├── settings.py      # GET/POST /api/settings
│   │       ├── characters.py    # GET /api/characters, animations, icon preview
│   │       ├── memory.py        # sessions, facts, clear, activate
│   │       ├── mcp.py           # MCP servers CRUD + status
│   │       ├── vault.py         # vault files CRUD + search + upload
│   │       ├── providers.py     # models list per provider
│   │       └── tts.py           # TTS preview
│   ├── config/
│   │   └── settings.py          # Settings manager with dict/json read/write, dot-path access
│   ├── core/
│   │   ├── agent.py             # Streaming agent loop (native tools + text-fenced fallback)
│   │   ├── context_builder.py   # System prompt template using string.Template
│   │   ├── context_manager.py   # Token-budget-aware context selection (priority scoring)
│   │   ├── memory.py            # SQLite memory with async writes, embeddings, summarization, facts
│   │   ├── relationship.py      # Per-character relationship tracking (sentiment, stage, decay)
│   │   ├── vault.py             # Standalone markdown vault manager (search, read, write, tags)
│   │   └── llm/
│   │       ├── base.py          # LLMProvider ABC with supports_native_tools, stream_with_tools
│   │       ├── claude.py        # Claude provider with native tool_use
│   │       ├── gemini.py        # Gemini via OpenAI-compatible endpoint
│   │       ├── koboldai.py      # KoboldAI with text-fenced tool blocks
│   │       ├── llamacpp.py      # LlamaCpp with text-fenced tool blocks
│   │       ├── ollama.py        # Ollama with text-fenced tool blocks
│   │       ├── openai_compat.py # OpenAI-compat (OpenRouter, Groq, ChatGPT, Z.AI, SiliconFlow)
│   │       └── router.py        # LLMRouter + fallback embeddings (provider / local / disabled)
│   ├── mcp/
│   │   ├── client.py            # MCP stdio client with reconnect + skill tool registration
│   │   └── servers/
│   │       ├── filesystem/server.py  # Path-restricted file read/write
│   │       ├── screenshot/server.py  # Screenshot capture (text output for non-vision LLMs)
│   │       ├── shell/server.py       # Shell with configurable allowlist (safe / unrestricted)
│   │       └── system/server.py      # System info: cpu, memory, processes, clipboard, time, reminder
│   ├── skills/
│   │   ├── loader.py            # SkillLoader — auto-discovers skills/*/skill.py
│   │   ├── web_search/          # DuckDuckGo web search
│   │   ├── reminder/            # Timer-based reminder
│   │   ├── note/                # Save notes to vault
│   │   ├── read_vault/          # Search + retrieve from vault
│   │   └── summarize_url/       # Fetch + summarize a URL
│   ├── utils/
│   │   ├── tokens.py            # Token estimation (tiktoken / char-4 heuristic)
│   │   └── icon_generator.py    # PIL-based character icon generation
│   └── voice/
│       ├── pipeline.py          # Voice capture → VAD → STT (threaded)
│       ├── vad.py               # Silero VAD wrapper
│       ├── stt/
│       │   ├── base.py
│       │   ├── faster_whisper_provider.py
│       │   ├── groq_whisper_provider.py
│       │   ├── openai_whisper_provider.py
│       │   ├── router.py
│       │   └── whispercpp_provider.py
│       └── tts/
│           ├── base.py
│           ├── alltalk_provider.py
│           ├── coqui_local_provider.py
│           ├── edge_tts_provider.py  # SSML prosody with emotion-to-rate/pitch
│           ├── elevenlabs_provider.py
│           ├── kokoro_provider.py
│           ├── openai_tts_provider.py
│           ├── openvoice_provider.py
│           ├── piper_provider.py
│           ├── router.py
│           └── speecht5_provider.py
├── characters/                   # 31 character directories
│   ├── default/                  # (anim/, icon.png, index.yaml, model.vrm)
│   └── {name}/                   # Each: icon.png, index.yaml, model.vrm, anim/*.vrma
├── frontend/
│   ├── css/
│   │   └── style.css            # Theme variables, layout, settings, chat, avatar
│   ├── icons/                    # Fonts, logos
│   ├── index.html                # Main SPA page
│   ├── js/
│   │   ├── app.js                # Main frontend logic
│   │   ├── audio-utils.js        # Audio DSP utilities
│   │   ├── avatar.js             # VRM renderer (Three.js + @pixiv/three-vrm)
│   │   ├── frequency-analyzer.js # FFT-based viseme detection
│   │   ├── visemes.js            # Phoneme→viseme mappings
│   │   └── vrm-animation.js      # VRMA animation loader
│   ├── vendor/                   # Three.js + three-vrm bundles
│   └── vrm-icon-renderer.html    # Standalone icon renderer
└── data/
    ├── conversations.db          # SQLite memory storage
    ├── relationship.db           # SQLite relationship storage
    ├── settings.json             # User settings (JSON)
    └── vault/                    # Markdown vault files
```

## Architecture Flow
```
Browser (Three.js + VRM)          FastAPI Backend
┌─────────────────────┐           ┌──────────────────────────────┐
│  app.js             │  WebSocket│  ws/handler.py (ws_chat)     │
│  ├─ WebSocket client│◄─────────►│  ├─ Agent.handle_user_input  │
│  ├─ TTS queue       │           │  ├─ TTSRouter.synthesize     │
│  ├─ Chat UI         │  REST API │  ├─ Sentiment analysis       │
│  ├─ Settings panel  │◄─────────►│  └─ Fact extraction          │
│  └─ Session mgmt    │           │                              │
│                     │           │  agent.py                    │
│  avatar.js          │           │  ├─ Native tool_use (Claude) │
│  ├─ Three.js render │           │  ├─ Text-fenced [[tool]]     │
│  ├─ Lip sync (FFT)  │           │  ├─ Emotion/Expression tags  │
│  ├─ VRM expressions │           │  ├─ ├─ MCP tool integration  │
│  ├─ Hit-area click  │           │  └─ ├─ Skill tool integration│
│  │  (head/chest/… → │           │                              │
│  │   play .vrma)    │           │  context_builder.py          │
│  ├─ VRMA animations │           │  └─ character template       │
│  │  (idle blink,    │           │      + vault injection       │
│  │   idle_curious,  │           │      + summary + thinking    │
│  │   every 8–15s)   │           │                              │
│  └─ Blink/Saccade   │           │  context_manager.py          │
│                     │           │  └─ Token budget context     │
│  frequency-analyzer │           │      selection by priority   │
│  └─ Viseme classifier│          │                              │
│                     │           │  LLM Router ─► Claude (native tools)
│  visemes.js         │           │               Gemini / Groq / OpenAI
│  └─ Phoneme→Viseme  │           │               Ollama / LlamaCpp / KoboldAI
│                     │           │                              │
│  vrm-animation.js   │           │  TTS Router ─► EdgeTTS (SSML prosody)
│  └─ VRMA parser     │           │               OpenVoice / ElevenLabs / ...
│                     │           │                              │
│                     │           │  VoicePipeline (thread)      │
│                     │           │  └─ VAD → STT → callback     │
│                     │           │                              │
│                     │           │  MCPClient (12 tools total)  │
│                     │           │  ├─ Shell (safe/unrestricted)│
│                     │           │  ├─ Filesystem (path-restrict)│
│                     │           │  ├─ Screenshot               │
│                     │           │  ├─ System (cpu/memory/etc)  │
│                     │           │  └─ Skills (5 auto-discovered)│
│                     │           └──────────────────────────────┘
```

## Communication Protocol
- **WebSocket** (`/ws/chat`): bidirectional streaming
  - Client→Server: `user_message`, `voice_output_on/off`, `voice_input_on/off`, `speak`, `change_character`, `change_system_prompt`
  - Server→Client: `chat_append` (streaming text), `speak_tts` (base64 WAV), `voice_state`, `emotion`, `action`, `thinking`, `error`, `session` (id on connect)
- **REST API**: Settings CRUD, character list, animations, providers, memory/sessions, MCP status, vault files

## Agent Pipeline (agent.py)
1. LLM provider selected from settings (hot-swappable per session)
2. If provider supports native tools (Claude) → `stream_with_tools()` with tool definitions
3. If provider is text-only → inject tool instructions in prompt, parse `\`\`\`tool` fences
4. Stream tokens: detect `__emotion__`, `__expression__`, `__thinking__`, `__roleplay__` tags inline
5. Strip display markers (`[[tag]]`, `))`, `//`)
6. MCP tool calls routed through `MCPClient` (server tools first, then skill tools)
7. 5-iteration retry loop
8. `finally` block always yields `finished: True` with accumulated response

## Memory System (memory.py)
- SQLite-backed per-session storage (async writes via `run_in_executor`)
- Embedding-based retrieval (provider or local `sentence-transformers` fallback)
- TurboPuff/integer embeddings with cosine similarity
- Keyword overlap dedup for fact extraction (Jaccard > 0.65)
- Auto-summarization at configurable threshold (default 40 messages)
- Session management (CRUD + activate)

## Context Manager (context_manager.py)
- Priority-ordered message selection: recent → relevant → important facts → summary
- Token budget estimation (`tiktoken` for OpenAI, `len(text)//4` heuristic)
- Adaptive truncation: drops lowest-priority messages when budget exceeded
- Settings: `memory.context_window`, `memory.retrieval_k`, `memory.summarize_threshold`, `memory.summarize_keep`

## Skill System (skills/loader.py)
- Auto-discovers `skills/*/skill.py` at startup
- Each skill provides `name`, `description`, `parameters`, `execute(args) → str`
- Registered in `MCPClient` as local tools (not separate MCP servers)
- 5 built-in skills: `web_search`, `reminder`, `note`, `read_vault`, `summarize_url`

## Voice Pipeline
- Background thread: sounddevice capture → Silero VAD → STT (`ThreadPoolExecutor`)
- TTS: per-sentence synthesis, sent as base64 WAV over WebSocket
- EdgeTTS SSML prosody: emotion → rate/pitch mapping (`_EMOTION_PROSOBY_MAP`)
- OpenVoice: prefers `voice.pth` (fast), fallback `voice.wav` (extract → auto-save .pth)
- TTS lock only for `openvoice` engine; all other engines are concurrent-safe

## Key Design Decisions
- Native tool calling only enabled when API key is configured
- Skills are local tools in MCPClient (no stdio overhead)
- All 6 LLM providers read `max_tokens` from settings
- Fact dedup uses word-set Jaccard similarity > 0.65
- Character YAML extended with: `quirks`, `memory_bias`, `forbidden`, `mood_baseline`, `mood_volatility`
- Avatar idle behavior: random micro-animations every 8–15 seconds
- Avatar hit areas: head, chest, groin, leg → plays corresponding `.vrma`
