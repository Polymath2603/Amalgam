# Amalgam

A voice-first AI companion with 3D VRM avatar, MCP tool integration, and multi-provider LLM support.

## Architecture

- **Frontend**: Browser-based UI with Three.js + @pixiv/three-vrm for 3D avatar rendering
- **Backend**: FastAPI + WebSocket server on port 8000
- **AI Core**: Agentic loop with multiple LLM providers (OpenRouter, Gemini, Ollama, etc.)
- **Voice Pipeline**: Edge-TTS synthesis, Silero VAD, Faster-Whisper STT
- **Tools**: MCP (Model Context Protocol) with Shell, Screenshot, Filesystem, and more
- **Characters**: 17 characters with personality, voice, and system prompts in `characters/*/`

## How to Run

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the Backend
```bash
python -m backend
```

### 3. Open the UI
Navigate to `http://localhost:8000` in your browser.

### 4. Customizing the Avatar
Place `.vrm` files in `user_data/avatars/`. Per-character models go in `characters/$name/model.vrm`.

## Features

- **3D VRM Avatar**: Real-time lip-sync and emotion expressions
- **Voice Chat**: Speak and listen with configurable voices per character
- **MCP Tools**: Run commands, browse files, take screenshots, and more
- **Multi-Provider**: OpenRouter, Gemini, Groq, ChatGPT, Z.AI, SiliconFlow, Ollama
- **Themes**: Dark, Midnight, Light, Nord with accent color picker
- **Session History**: Persistent conversation sessions with per-session management
- **17 Characters**: Each with unique personality, voice, and system prompt
