# Codebase Architecture

## Directory Tree
```
/home/leonardo/Workplace/k/
├── backend/
│   ├── app.py                   # FastAPI app factory, lifespan, mount static/media
│   ├── api/
│   │   ├── deps.py              # Depends() — shared component injection
│   │   ├── telegram.py          # Telegram bot interface
│   │   ├── ws/
│   │   │   ├── handler.py       # WebSocket chat handler (Realtime Voice Loop)
│   │   │   └── tts_service.py   # TTS synthesis + sentence streaming
│   │   └── routes/
│   │       ├── settings.py      # GET/POST /api/settings
│   │       ├── characters.py    # GET /api/characters, animations
│   │       ├── memory.py        # sessions, facts, clear
│   │       └── ...
│   ├── core/
│   │   ├── agent.py             # Streaming agent loop + dynamic truncation
│   │   ├── context_builder.py   # System prompt template + vault injection
│   │   ├── memory.py            # SQLite memory + ChromaDB embeddings
│   │   ├── relationship.py      # Per-character tracking
│   │   ├── vault.py             # Markdown vault manager
│   │   └── llm/                 # Multi-provider LLM abstraction
│   ├── mcp/
│   │   ├── client.py            # MCP stdio client
│   │   └── servers/             # Tool servers (shell, screenshot, system, etc.)
│   ├── skills/                  # Auto-discovered skill modules
│   └── voice/
│       ├── pipeline.py          # Voice capture → VAD → STT
│       ├── vad.py               # WebRTC VAD
│       └── tts/                 # Text-to-speech providers
├── webui/                       # Consolidated Frontend
│   ├── index.html               # Main SPA (supports ?mode=companion)
│   ├── css/style.css            # Themes + Overlay styles
│   └── js/
│       ├── app.js               # Main logic (Environment-aware)
│       ├── avatar.js            # VRM renderer
│       └── ...
├── cli/
│   ├── __init__.py              # Standard CLI mode
│   └── companion.py             # Companion mode (Terminal + Overlay)
├── data/                        # Persistent user data (characters, settings, DBs)
└── desktop/
    └── tauri/                   # Desktop wrapper (handles overlay transparency)
```

## Architecture Flow
```
Terminal / Telegram / Browser     FastAPI Backend
┌─────────────────────┐           ┌──────────────────────────────┐
│  Interfaces         │  WebSocket│  ws/handler.py               │
│  ├─ CLI / Companion │◄─────────►│  ├─ Task-managed Agent Loop  │
│  ├─ Telegram Bot    │           │  ├─ Realtime Voice Interrupt │
│  └─ Desktop Overlay │  REST API │  └─ TTS Streaming            │
│                     │◄─────────►│                              │
│  Components         │           │  agent.py                    │
│  ├─ VRM Renderer    │           │  ├─ Native tool_use          │
│  ├─ Voice Loop      │           │  ├─ Token-budget aware       │
│  └─ State Machine   │           │  └─ Emotion/Action parsing   │
└─────────────────────┘           └──────────────────────────────┘
```

## Communication Protocol
- **WebSocket** (`/ws/chat`): bidirectional streaming. Handles `tts_interrupt` for Moshi-like realtime behavior.
- **REST API**: Settings, characters, and memory management.

## Key Modes
- **Desktop:** Full GUI experience.
- **Companion:** Terminal chat + transparent avatar overlay + 46s sleep cycle.
- **Telegram:** Remote text/voice interaction with security allowlist.
- **CLI:** Pure terminal interaction.

## Design Decisions
- **Consolidated WebUI:** The same frontend serves the full app and the overlay (via CSS classes).
- **Environment-Aware:** JS files detect `tauri:` vs `http:` to set `BASE_URL`.
- **Task Management:** Assistant responses are tracked as `asyncio.Task` to allow instant cancellation on user interruption.
- **Standardized Paths:** All character assets and animations are served from `data/characters/`.
