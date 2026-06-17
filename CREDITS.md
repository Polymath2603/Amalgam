# CREDITS

Amalgam stands on the shoulders of giants. This project incorporates ideas,
architectures, and inspiration from the following open-source projects and works.

## Core AI / Agent Architecture
- **Open-LLM-VTuber** — Voice interrupt/barge-in architecture, WebSocket streaming design
- **SemperAI/Amica** — Life state machine (idle→bored→sleeping), 14-emotion avatar system
- **ChatVRM** — Emotion tag system (`[emotion]` tags in LLM responses)
- **Wayland** — Mission Control live agent visualization (swarm D3.js graph)
- **Anthropic Claude** — Chain-of-command escalation patterns, agent planning architecture

## Technical Foundations
- **Three.js** — 3D rendering for VRM avatars
- **@pixiv/three-vrm** — VRM model loading and manipulation
- **FastAPI** — WebSocket and REST API framework
- **D3.js** — Force-directed graph visualization (swarm UI)
- **LiteLLM** — Multi-provider LLM routing
- **DuckDuckGo Search** — Web search capabilities
- **openWakeWord** — Wake word detection

## Memory & Knowledge
- **sqlite-vec** / **FTS5** — Hybrid search architecture
- **Chunk Norris** — Chunking strategies inspiration

## UI/UX
- **Material Icons** — Icon set
- **Inter font** — UI typography

---

*If we've missed anyone, please open an issue and we'll correct it promptly.*
