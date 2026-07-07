# Amalgam

> **⚠ Archived — not under active development.**
> This project is being discontinued in favor of a plugin for
> [Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous
> Research), which already solves the memory/skill/self-learning/
> scheduling side of this vision at a scale a solo project can't match.
> This repo is left as a working, tested reference — see
> [`LEGACY_NOTICE.md`](./LEGACY_NOTICE.md) for the full reasoning and
> [`AUDIT_REPORT.md`](./AUDIT_REPORT.md) for what was found and fixed to
> get it to this state.

A voice-first AI companion with 3D VRM avatar, MCP tool integration, multi-provider LLM support, extensible skills, and persistent memory.

## What is Amalgam?

Amalgam is a voice-first AI companion that runs locally on your machine. It features a 3D VRM avatar with lip-sync and emotions, multi-provider LLM support, persistent memory with semantic search, and MCP tool integration. It remembers you across sessions, learns your preferences over time, and can be extended with custom skills and characters.

### Key Features

| Feature | Status |
|---|---|
| 3D VRM Avatar (lip-sync, emotions, idle) | Stable |
| Voice Chat (TTS / STT) | Stable |
| Multi-Provider LLM | Stable |
| Native Function Calling | Stable |
| MCP Tool Servers | Stable |
| Skill System (auto-discovered) | Stable |
| Persistent Memory (SQLite + Embeddings) | Stable |
| FTS5 Full-Text Search | New |
| User Profile (auto-learning across sessions) | New |
| Reflective Agent | New |
| Planning Agent (task decomposition) | New |
| Parallel Tool Calls | New |
| Metrics & Cost Tracking | New |
| AI Company plugin (optional planning brain, see below) | New |
| Layout / Position Persistence | Done |
| URL Tab Persistence | Done |
| Theme System | Done |
| Character System | Stable |
| Vault (markdown notes) | Stable |
| Session History | Stable |

## Architecture

```
+-----------------------------------------------------+
|                    Frontend                          |
|  WebUI (JS/HTML) <--> WebSocket <--> CLI <--> Telegram|
+--------------------------+--------------------------+
                           |
+--------------------------v--------------------------+
|              FastAPI Backend (app.py)                |
|  +-----------+ +----------+ +--------------------+  |
|  | WS Handler| | REST API | | Dependency Inject  |  |
|  +-----+-----+ +----------+ +--------------------+  |
+--------+-------------------------------------------+
         |
+--------v-------------------------------------------+
|  Agent Layer                                        |
|  +----------+ +--------------+ +-----------------+  |
|  | Basic    | | Reflective   | | Planning        |  |
|  | Agent    | | Agent        | | Agent           |  |
|  +----+-----+ +------+-------+ +--------+--------+  |
+-------+------------------+-------------------+-------+
        |                  |                   |
+-------v--------+ +------v------+ +---------v--------+
| LLM Providers  | | Memory       | | MCP Tools        |
| Gemini, Claude | | SQLite+FTS5  | | Shell, FS, etc.  |
| Ollama, etc.   | | ChromaDB     | | Skills           |
+----------------+ +--------------+ +------------------+
```

**Backend:** Python 3.10+ / FastAPI / uvicorn
**Frontend:** Vanilla JavaScript (ES modules, no build step)
**WebSocket:** Real-time bidirectional chat
**Voice Pipeline:** STT -> LLM -> TTS with sentence-level streaming
**Avatar:** Three.js + @pixiv/three-vrm for 3D VRM rendering

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js (optional, for VRM icon generation and dev tooling)

### Installation

```bash
git clone https://github.com/your-username/amalgam.git
cd amalgam
pip install -r requirements.txt
```

### Configuration

Create a `.env` file or set environment variables:

```bash
# Server
AMALGAM_PORT=8000
AMALGAM_HOST=0.0.0.0

# Data directory
AMALGAM_DATA_DIR=data/

# Shell MCP mode (safe or unrestricted)
AMALGAM_SHELL_MODE=safe
```

Settings are stored in `data/settings.json` and can be configured via the Settings UI or by editing the file directly.

### Running

```bash
# Launch web UI (default)
python main.py

# Launch with specific port
python main.py --port 3000

# Launch interactive CLI
python main.py cli

# Launch desktop app (Tauri)
python main.py desktop

# Show metrics report
python main.py stats
```

Then open `http://localhost:8000` in your browser.

### First-Time Setup

On first launch, Amalgam shows a setup wizard to configure:
1. **LLM Provider** - Choose from 20+ providers (Gemini, Claude, Ollama, etc.)
2. **Voice** - Configure STT engine and TTS engine
3. **Character** - Select or create a companion character

## Features

### 3D VRM Avatar

- Real-time lip-sync using viseme mapping (15 viseme shapes)
- Emotion expressions (happy, sad, angry, surprised, etc.)
- Idle animations with micro-animations (curiosity, amusement, admiration)
- Click-to-interact hit areas
- Roleplay animation triggers from conversation context
- GPU tier detection for adaptive quality
- Sprite avatar fallback for low-end devices

### Voice Chat

- **Speech-to-Text (STT):** Browser Web API, Faster-Whisper, Groq Whisper, OpenAI Whisper, Whisper.cpp
- **Text-to-Speech (TTS):** Edge-TTS (free), ElevenLabs, OpenAI TTS, AllTalk, Piper, Coqui, Kokoro, Azure, Deepgram, DashScope, Volcengine, MLX, RVC
- SSML prosody mapping for emotion-to-vocal-tone expression
- Sentence-level streaming TTS for low latency
- Wake word detection (OpenWakeWord, Snowboy)

### Multi-Provider LLM

Supports 20+ LLM providers, hot-swappable per session:

| Provider | Native Tool Calling |
|---|---|
| Claude (Anthropic) | tool_use |
| Gemini (Google) | function_declarations |
| OpenAI / ChatGPT | functions |
| Groq | functions |
| OpenRouter | varies |
| Ollama (local) | varies |
| DeepSeek | functions |
| Mistral | functions |
| Together AI | functions |
| SiliconFlow | functions |
| Z.AI | functions |
| Azure OpenAI | functions |
| AWS Bedrock | varies |
| GCP Vertex AI | varies |
| Alibaba (DashScope) | functions |
| Hugging Face | varies |
| llama.cpp (local) | varies |
| KoboldAI (local) | varies |
| OpenCode | varies |

Falls back to text-fenced ` ```tool ` blocks for non-native providers.

### MCP Tool Integration

Built-in MCP (Model Context Protocol) tool servers:
- **Shell** - Execute shell commands (configurable allowlist)
- **Filesystem** - Read/write files (path-restricted)
- **Screenshot** - Screen capture with image analysis
- **System** - CPU/memory/clipboard/process monitoring

Permission levels: `readonly`, `confirm`, `full`

### Skill System

Auto-discovered Python modules in `backend/skills/`. Built-in skills include:
- Web search
- Reminders
- Note-taking
- Vault reading
- URL summarization

### AI Company Plugin

An optional "thinking brain" that routes complex tasks through the separate
AI Company n8n harness — a 23-agent pipeline that plans, architects,
splits, reviews, and tests — before the main LLM responds. The model then
reasons from a detailed plan instead of improvising cold. The harness
itself (n8n workflow JSON + per-agent role definitions) ships as its own
package alongside Amalgam, not inside this repo — see its own
`ai-company/README.md` for the full agent roster and n8n import steps.

**How it works**: implemented as a normal `BasePlugin`
(`backend/plugins/ai_company/`) using the `on_system_prompt` hook — the
same hook every plugin already gets, no changes needed anywhere else in
the agent loop. It POSTs the user's message to your n8n webhook, waits for
a structured plan, and prepends it to the system prompt. If n8n is
unreachable or times out, it fails silently and the normal flow continues
— this is meant to be a strict enhancement, never a hard dependency.

**Modes** (`ai_company.mode` in Settings → AI Company):
| Mode | Behavior |
|---|---|
| `off` | Never called |
| `auto` (default) | Called only when the message looks like a build/design/implement task |
| `on` | Called for every message |

**Setup**:
1. Deploy the two n8n workflows from the AI Company harness (see its own
   README for the full agent roster and n8n import steps).
2. Set `ai_company.webhook_url` in Settings → AI Company to your n8n
   instance's `POST /webhook/company-job` URL.
3. Pick a mode. `auto` is the sane default — it won't fire for "what's the
   weather" but will for "build me a REST API with auth."

**Controls**:
- TUI: `/company [status | on | off | auto | run <task>]`, plus a live
  status indicator in the header (`◑` auto, `⚡` on, `⚙` running, `✓` done,
  `✗` error).
- WebUI: the psychology-icon button next to the mic/speaker toggles in the
  chat header — click cycles off → auto → on, badge shows live run status.
- The LLM can also call it directly as a tool (`run_company`) for one-off
  planning requests mid-conversation.

### Persistent Memory

Five functional partitions, intentionally not five identically-structured files:

| Partition | Where it lives | What it holds |
|---|---|---|
| Working | `backend/core/memory/working.py` | Recent turns, bounded, no persistence |
| Episodic | `backend/core/memory/episodic.py` (per session) | What happened, when |
| Semantic | `backend/core/memory/semantic.py` + `hybrid.py`/`fts.py` | Facts + embeddings/keyword index |
| Procedural | `backend/skills/` + `backend/core/skills/curator.py` | *How* to do things — SKILL.md definitions |
| User model | `backend/core/user_profile.py` | Preferences/expertise learned across sessions |

- SQLite with async writes
- ChromaDB embedding-based retrieval
- FTS5 full-text search
- Auto-summarization and compaction
- Keyword + TF-IDF relevance scoring
- Fact extraction with deduplication

### Self-Learning & Corrections

- Persistent user profile (auto-learned across sessions)
- Preference tracking
- Automatic skill creation from observed patterns
- User correction feedback loop

### Relationship System

- Per-character sentiment tracking with decay
- Relationship stage progression (stranger -> acquaintance -> friend -> close friend -> intimate)
- Injected as context to influence conversation tone

### Character System

YAML-defined characters with personality, voice, quirks, forbidden behaviors, VRM models, and animation sets.

### Vault

Standalone markdown note system with search, tags, and automatic context injection.

### Context Management

Token-budget-aware message selection, adaptive truncation, priority-based context window.

### Companion Mode

Proactive AI that checks in when idle. Configurable idle delay, proactive interval, and time awareness.

## Configuration

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AMALGAM_PORT` | `8000` | Server port |
| `AMALGAM_HOST` | `0.0.0.0` | Server bind address |
| `AMALGAM_DATA_DIR` | `data/` | Data directory for settings, memory, vault |
| `AMALGAM_SHELL_MODE` | `safe` | Shell MCP mode (`safe` or `unrestricted`) |
| `AMALGAM_SHELL_ALLOWED_COMMANDS` | - | Comma-separated shell command prefixes |
| `AMALGAM_CORS_ORIGINS` | - | Comma-separated CORS origins (overrides defaults) |
| `NO_BROWSER` | - | Set to disable auto-opening browser on start |

### Settings Reference

Settings are stored in `data/settings.json`. Key configuration categories:

- **provider.active** - Current LLM provider
- **provider.{name}.api_key** - API key for a provider
- **provider.{name}.model** - Model for a provider
- **voice.engine** - TTS engine
- **voice.stt_engine** - STT engine
- **voice.input_enabled** / **voice.output_enabled** - Voice I/O toggles
- **character.active** - Active character ID
- **ui.theme** - UI theme (dark, midnight, light, nord)
- **ui.language** - UI language (en, zh)
- **agent.type** - Agent type (basic, reflective, planning, reflective_planning)
- **llm.temperature** - LLM temperature (0-2)
- **mcp.servers** - MCP server configurations
- **companion.enabled** - Companion mode toggle

### LLM Provider Setup

1. Open Settings > Provider tab
2. Select your provider from the dropdown
3. Enter your API key
4. Select a model
5. Click "Test Connection" to verify

### Voice Provider Setup

1. Open Settings > Voice tab
2. Set STT Engine (browser, faster-whisper, openai-whisper, groq-whisper, whispercpp)
3. Set TTS Engine (edge-tts, elevenlabs, openai-tts, etc.)
4. Configure provider-specific settings (API keys, voices, etc.)
5. Click "Preview" to test TTS

### MCP Server Setup

MCP servers are configured in Settings > MCP tab or via the `/mcp` slash command. Each server has:
- `name` - Display name
- `command` - Executable command
- `args` - Command arguments
- `enabled` - Toggle on/off

## Adding Characters

Create `characters/<name>/index.yaml`:

```yaml
name: "Character Name"
voice: "en-US-AriaNeural"
personality: "warm, curious"
characteristics: "friendly, knowledgeable"
interaction_style: "engaging, detailed"
system_prompt: "You are..."
vocabulary: ["favorite phrase", "catch phrase"]
dialogue_examples: ["User: ... Assistant: ..."]
quirks: ["sometimes speaks in third person when excited"]
forbidden: ["never uses slang"]
mood_baseline: 0.6
mood_volatility: 0.3
```

Place `model.vrm` in the directory for a 3D avatar, `voice.pth` / `voice.wav` for OpenVoice cloning.

## Custom Skills

Create `backend/skills/<name>/skill.py`:

```python
from backend.skills.base import Skill

class MySkill(Skill):
    name = "my_skill"
    description = "What my skill does"
    parameters = {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
        },
        "required": ["param1"],
    }

    async def execute(self, args):
        return "result"
```

Skills are auto-discovered at startup and exposed as MCP tools.

## API Documentation

See [docs/API.md](docs/API.md) for complete REST and WebSocket API documentation.

## Frontend Module Guide

See [docs/MODULES.md](docs/MODULES.md) for documentation on the frontend ES module system.

## Project Structure

```
backend/
  __main__.py              # Entry point
  app.py                   # FastAPI app factory
  paths.py                 # Central path definitions
  cli_stats.py             # python -m backend stats
  api/
    deps.py                # Dependency injection
    ws/
      handler.py           # WebSocket chat handler + TTS service
      tts_service.py       # Sentence-level TTS streaming
    routes/
      settings.py          # Settings CRUD + provider test
      characters.py        # Character/animation/voice/model API
      commands.py          # Slash command definitions
      companion.py         # Companion mode settings
      mcp.py               # MCP server/tool management
      memory.py            # Session/fact/memory API
      metrics.py           # Tool analytics + per-turn metrics
      push.py              # Push notification registration
      relationship.py      # Relationship stats
      setup.py             # First-run setup wizard
      tts.py               # TTS preview endpoint
      vault.py             # Vault file management
    server.py              # Re-export of app
    telegram.py            # Telegram bot frontend
  cli/
    companion.py           # CLI companion mode
  core/
    agent/
      base.py              # Base agent class
      basic_agent.py       # Single-turn agent
      reflective_agent.py  # Reflective agent (re-evaluates every 5 turns)
      planning_agent.py    # Task decomposition agent
      factory.py           # Agent factory
      hooks.py             # Agent hooks
      stream_processor.py  # Streaming output processor
      analytics.py         # Agent analytics
      permissions.py       # Agent permission system
    companion/
      events.py            # Companion event types
      scheduler.py         # Proactive check-in scheduler
    config/
      settings.py          # Settings manager with dot-path access
      character_schema.py  # Character validation schema
      schema.py            # Settings schema definitions
      models.py            # Pydantic models
    llm/
      router.py            # Multi-provider LLM abstraction
      litellm_provider.py  # LiteLLM integration
      cost_router.py       # Cost-aware routing
    mcp/
      client.py            # MCP stdio client with reconnect
    memory/
      manager.py           # Memory manager
      hybrid.py            # Hybrid search (semantic + keyword + TF-IDF)
      fts.py               # FTS5 full-text search
      cache.py             # Memory cache
      episodic.py          # Episodic memory
      semantic.py          # Semantic memory (ChromaDB)
      working.py           # Working memory
      consolidator.py      # Memory compaction
      session_index.py     # Session indexing
    metacognitive/
      engine.py            # Meta-cognitive reasoning
      adaptation_engine.py # Adaptive strategy selection
      delta_evaluator.py   # Change evaluation
      strategy_selector.py # Strategy selection
    orchestrator/
      engine.py            # Multi-agent orchestration
      blackboard.py        # Shared blackboard
      escalation.py        # Task escalation
      sandbox.py           # Sandboxed execution
      state.py             # Orchestration state
    plugins/
      example_plugin.py    # Example plugin
    self_learning/
      auto_skill.py        # Automatic skill creation
      corrections.py       # User correction tracking
      improvement.py       # Self-improvement loops
      preferences.py       # Preference learning
    skills/
      curator.py           # Skill curation
    utils/
      tokens.py            # Token estimation
      wav.py               # WAV audio utilities
      icon_generator.py    # Character icon generation
    voice/
      tts/                 # TTS providers (edge-tts, elevenlabs, etc.)
  skills/                  # Auto-discovered skill modules
  tests/                   # Test suite (pytest)
  utils/
    tokens.py              # Token estimation
    wav.py                 # WAV audio utilities
  voice/
    pipeline.py            # Microphone + VAD + STT pipeline
    vad.py                 # Voice activity detection
    stt/                   # Speech-to-text providers
    tts/                   # Text-to-speech providers
webui/                     # Browser-based UI (JS, HTML, CSS)
  index.html               # Main HTML entry
  manifest.json            # PWA manifest
  sw.js                    # Service worker
  css/style.css            # Stylesheet
  icons/                   # Icons, fonts, images
  js/
    app.js                 # Frontend orchestrator (entry point)
    avatar.js              # VRM avatar rendering (Three.js)
    visemes.js             # Viseme mapping definitions
    viseme-scheduler.js    # Viseme timing scheduler
    adaptive-lipsync.js    # Adaptive lip-sync manager
    advanced-lipsync.js    # Advanced lip-sync engine
    vrm-animation.js       # VRM animation loading/playback
    idle-manager.js        # Idle animation manager
    sprite-avatar.js       # 2D sprite avatar fallback
    audio-utils.js         # Audio analysis utilities
    frequency-analyzer.js  # Frequency analysis for lip-sync
    custom-select.js       # Custom select dropdowns
    i18n.js                # Internationalization (en, zh)
    metrics.js             # Metrics dashboard
    swarm.js               # Agent swarm visualization (D3.js)
    modules/               # ES modules (see docs/MODULES.md)
  locales/                 # Translation files
    en.json                # English
    zh.json                # Chinese
  vendor/                  # Vendored libraries (Three.js, VRM, D3)
  tests/                   # Frontend tests
```

## Slash Commands

Available in chat input (prefix with `/`):

| Command | Description |
|---|---|
| `/clear` | Clear history and start fresh |
| `/new` | Start a new session |
| `/resume` | Show last 5 turns of current session |
| `/rename <title>` | Rename current session |
| `/status` | Show provider, model, session |
| `/compact` | Force memory compaction |
| `/help` | Show available slash commands |
| `/provider <name>` | Switch AI provider |
| `/model <name>` | Switch model for current provider |
| `/settings [key] [val]` | Show or set configuration values |
| `/memory` | Show memory stats |
| `/stats` | Show tool usage analytics |
| `/health` | Run live service health checks |
| `/theme <name>` | Switch UI theme (dark, midnight, light, nord) |
| `/character <name>` | Load a character |
| `/profile <name>` | Switch settings profile |
| `/think` | Toggle thinking display on/off |
| `/companion` | Toggle companion mode on/off |
| `/permission <level>` | Set permission level (readonly, confirm, full) |
| `/mcp [list \| connect \| disconnect \| tools] <server>` | Manage MCP tool servers |
| `/company [status \| on \| off \| auto \| run <task>]` | Control the AI Company thinking plugin |
| `/plan [create \| list \| run \| cancel]` | Manage multi-step plans |
| `/vault <query>` | Search vault notes |
| `/direct` | Toggle direct mode — swaps to a plain agent, skipping planning/reflection layers |

## Development

### Running Tests

```bash
# Backend tests
cd backend
python -m pytest tests/

# Frontend tests (if using a test runner)
cd webui
npx vitest
```

### Project Conventions

- **Backend:** Python 3.10+ with type hints, async/await throughout
- **Frontend:** Vanilla JavaScript ES modules, no build step, no npm
- **Settings:** Dot-notation paths (e.g., `provider.active`, `voice.engine`)
- **WebSocket:** JSON messages with `type` field for routing
- **Error handling:** ServiceError class with user-friendly normalization

## Similar Projects

- [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) - Open-source LLM VTuber project
- [amica](https://github.com/semperai/amica) - VRM chat companion with voice

## License

See LICENSE file in the repository root.
