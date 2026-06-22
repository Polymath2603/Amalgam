# Environment Variables

All environment variables are prefixed with `AMALGAM_`.

---

## Server Configuration

| Variable | Default | Description |
|---|---|---|
| `AMALGAM_HOST` | `0.0.0.0` | Backend server bind address |
| `AMALGAM_PORT` | `8000` | Backend server port |
| `AMALGAM_BACKEND_URL` | `http://localhost:8000` | Public-facing URL of the backend (used for CORS and client references) |
| `AMALGAM_CORS_ORIGINS` | _(empty)_ | Comma-separated list of allowed CORS origins. Overrides the hardcoded allowlist. Set to `*` to allow all origins (not recommended in production). |

## Data & Paths

| Variable | Default | Description |
|---|---|---|
| `AMALGAM_DATA_DIR` | `<project_root>/data` | Root data directory for conversations, settings profiles, characters, skills, and vault files |
| `AMALGAM_CHARACTERS_DIR` | `<AMALGAM_DATA_DIR>/characters` | Directory containing character definitions |

## Translation

| Variable | Default | Description |
|---|---|---|
| `AMALGAM_DEEPLX_URL` | `http://localhost:1188/translate` | DeepLX translation service URL |

## LLM Providers

| Variable | Default | Description |
|---|---|---|
| `AMALGAM_OLLAMA_URL` | _(from settings)_ | Override the Ollama base URL at runtime |
| `AMALGAM_OPENCODE_URL` | _(from settings)_ | Override the OpenCode base URL at runtime |

## TTS (Text-to-Speech) Provider URLs

| Variable | Default | Description |
|---|---|---|
| `AMALGAM_ALLTALK_URL` | `http://127.0.0.1:7851` | AllTalk TTS service URL |
| `AMALGAM_COQUI_URL` | `http://127.0.0.1:5002` | Coqui Local TTS service URL |
| `AMALGAM_KOKORO_URL` | `http://127.0.0.1:8880` | Kokoro TTS service URL |
| `AMALGAM_PIPER_URL` | `http://127.0.0.1:5000` | Piper TTS service URL |
| `AMALGAM_RVC_URL` | `http://127.0.0.1:7897` | RVC TTS service URL |

## STT (Speech-to-Text) Provider URLs

| Variable | Default | Description |
|---|---|---|
| `AMALGAM_WHISPERCPP_URL` | `http://127.0.0.1:8080` | WhisperCPP STT service URL |

## Shell MCP Server

| Variable | Default | Description |
|---|---|---|
| `AMALGAM_SHELL_MODE` | `safe` | Shell execution mode: `safe` (allowed commands only), `restricted`, or `full` |
| `AMALGAM_SHELL_ALLOWED_COMMANDS` | _(extensive allowlist)_ | Comma-separated list of allowed shell command prefixes (used in `safe` mode) |
| `AMALGAM_SHELL_TIMEOUT` | `30` | Maximum seconds a shell command is allowed to run before being killed |

## CLI / Companion

| Variable | Default | Description |
|---|---|---|
| `AMALGAM_WS_URL` | `ws://localhost:8000/ws/chat` | WebSocket URL used by the CLI companion client |
| `AMALGAM_STT_TIMEOUT` | `30` | Seconds before STT transcription times out in the CLI client |
| `AMALGAM_SKIP_BACKEND` | _(not set)_ | Set to `1` to skip launching the backend server (desktop mode only) |

## Self-Learning Subsystem

### Preference Learner

| Variable | Default | Description |
|---|---|---|
| `AMALGAM_ENGAGEMENT_WINDOW` | `20` | Number of recent interactions to track for engagement analysis |
| `AMALGAM_VERBOSITY_WINDOW` | `10` | Number of recent responses to track for verbosity inference |
| `AMALGAM_LONG_RESPONSE_CUTOFF` | `500` | Word count above which a response is considered "long" |
| `AMALGAM_SHORT_RESPONSE_CUTOFF` | `100` | Word count below which a response is considered "short" |
| `AMALGAM_FOLLOWUP_THRESHOLD` | `3` | Number of consecutive user follow-ups before inferring engagement |

### Skill Improver

| Variable | Default | Description |
|---|---|---|
| `AMALGAM_SKILL_MIN_USAGE` | `2` | Minimum times a skill must be used to be considered "active" |
| `AMALGAM_SKILL_STALE_DAYS` | `14` | Days of inactivity after which a skill is considered stale and eligible for pruning |
