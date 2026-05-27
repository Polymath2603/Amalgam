# Godot Frontend (Amalgam)

## Development

### Prerequisites
- Godot 4.3+ (don't use 4.4 — the VRM addon targets 4.1-4.3)
- Python backend running on localhost:8000

### Run
1. Start the backend: `python main.py webui`
2. Open Godot, import project from `frontend/godot/project.godot`
3. Run (F5)

The avatar loads from `http://localhost:8000/characters/default/model.vrm`
WebSocket connects to `ws://localhost:8000/ws/chat`

## Architecture

```
scenes/
├── main.tscn     — Root scene (camera, lighting, UI)
├── main.gd       — Wires avatar + chat + WebSocket
└── avatar.tscn   — Avatar controller node

scripts/
├── avatar.gd       — Orchestrator: VRM load, emotions, blink, saccade, animations
├── lipsync.gd      — FFT-based viseme detection (port of frequency-analyzer.js)
├── visemes.gd      — Viseme data tables (port of visemes.js)
├── audio_utils.gd  — DSP utilities (port of audio-utils.js)
├── hit_areas.gd    — Clickable body zones (head/chest/groin/leg)
└── chat_client.gd  — WebSocket client → Python backend

ui/
├── chat_ui.tscn    — Chat interface (scene)
└── chat_ui.gd      — Chat interface logic

addons/
├── vrm/     — V-Sekai VRM importer (symlink to godot-vrm)
└── Godot-MToon-Shader/  — VRM toon shader (symlink)
```
