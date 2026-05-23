# K

A voice-first AI companion with 3D VRM avatar, MCP tool integration, multi-provider LLM support, extensible skills, and persistent memory.

## Quick Start

```bash
pip install -r requirements.txt
python -m backend
```

Open `http://localhost:8000` in your browser.

## Features

- **3D VRM Avatar** — Real-time lip-sync, emotion expressions, idle animations, click-to-interact hit areas
- **Voice Chat** — Speak and listen. Edge-TTS SSML prosody maps emotions to vocal tone. STT via browser, Faster-Whisper, Groq, or OpenAI Whisper
- **Multi-Provider LLM** — Claude (native tool calling), Gemini, Groq, ChatGPT, OpenRouter, Z.AI, SiliconFlow, Ollama, LlamaCpp, KoboldAI. Hot-swappable per session
- **Native Function Calling** — Claude `tool_use`, OpenAI-compat `functions`, Gemini `function_declarations`. Falls back to text-fenced `\`\`\`tool` blocks for non-native providers
- **MCP Tool Servers** — Shell (configurable allowlist), Filesystem (path-restricted), Screenshot (image-aware), System (CPU/memory/clipboard/processes)
- **Skill System** — Auto-discovered Python modules in `backend/skills/`. Built-in: web search, reminders, note-taking, vault reading, URL summarization
- **Persistent Memory** — SQLite with async writes, embedding-based retrieval, auto-summarization, keyword + TF-IDF relevance scoring, fact extraction with dedup
- **Relationship System** — Per-character sentiment tracking, decay, stage progression (stranger → intimate), injected as context
- **Character System** — YAML-defined characters with personality, voice, quirks, forbidden behaviors, VRM models, animation sets
- **Vault** — Standalone markdown note system with search, tags, automatic context injection
- **Context Management** — Token-budget-aware message selection, adaptive truncation, priority-based context window
- **Session History** — Persistent conversation sessions with restore, per-session management in the UI
- **Themes** — Dark, Midnight, Light, Nord with accent color picker

## Configuration

Settings are stored in `user_data/settings.json`. All settings have sensible defaults.

Key environment variables:
| Variable | Default | Description |
|---|---|---|
| `AMALGAM_PORT` | `8000` | Server port |
| `AMALGAM_HOST` | `0.0.0.0` | Server bind address |
| `AMALGAM_DATA_DIR` | `user_data/` | Data directory |
| `AMALGAM_SHELL_MODE` | `safe` | Shell MCP mode (`safe` or `unrestricted`) |
| `AMALGAM_SHELL_ALLOWED_COMMANDS` | — | Comma-separated shell command prefixes |

Configure providers, characters, voice, MCP servers, and memory settings via the Settings UI or by editing `user_data/settings.json` directly.

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

## Project Structure

```
backend/
├── __main__.py              # Entry point
├── app.py                   # FastAPI app factory
├── paths.py                 # Central path definitions
├── api/
│   ├── deps.py              # Dependency injection
│   ├── ws/                  # WebSocket handler + TTS service
│   └── routes/              # API route modules (settings, characters, mcp, vault, etc.)
├── config/
│   └── settings.py          # Settings manager with dot-path access
├── core/
│   ├── agent.py             # AI agent loop (streaming, tool calling, tag parsing)
│   ├── context_builder.py   # Prompt template + vault injection
│   ├── context_manager.py   # Token-budget-aware context selection
│   ├── memory.py            # SQLite memory with async writes, embeddings, summarization, facts
│   ├── relationship.py      # Per-character relationship tracking
│   ├── vault.py             # Standalone markdown vault manager
│   └── llm/                 # Multi-provider LLM abstraction with native tool calling
├── mcp/
│   ├── client.py            # MCP stdio client with reconnect
│   └── servers/             # Tool servers (shell, filesystem, screenshot, system)
├── skills/                  # Auto-discovered skill modules
├── utils/
│   ├── tokens.py            # Token estimation (tiktoken / char-4 heuristic)
│   └── icon_generator.py    # Character icon generation
└── voice/
    ├── pipeline.py          # Microphone + VAD + STT pipeline
    ├── vad.py               # Voice activity detection (Silero VAD)
    ├── stt/                 # Speech-to-text providers
    └── tts/                 # Text-to-speech providers (edge-tts, openvoice, elevenlabs, etc.)
```
