# Amalgam VRM Avatar Chat — Competitive Analysis Report

**Date:** 2026-06-20  
**Projects Analyzed:**
- **Amalgam** (`/home/leonardo/Workplace/k/`) — the project under development
- **Open-LLM-VTuber** (`/home/leonardo/Workplace/cloned/Open-LLM-VTuber-main/`)
- **amica** (`/home/leonardo/Workplace/cloned/amica/`)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Open-LLM-VTuber Analysis](#2-open-llm-vtuber-analysis)
3. [amica Analysis](#3-amica-analysis)
4. [Amalgam Current State](#4-amalgam-current-state)
5. [Feature Comparison Matrix](#5-feature-comparison-matrix)
6. [Recommendations](#6-recommendations)
7. [Priority Roadmap](#7-priority-roadmap)

---

## 1. Executive Summary

Three VRM/avatar chat projects were analyzed. Each takes a fundamentally different architectural approach:

| | Amalgam | Open-LLM-VTuber | amica |
|---|---------|-----------------|-------|
| **Avatar Type** | VRM (3D) | Live2D (2D) | VRM (3D) |
| **Backend** | Python (FastAPI + WebSocket) | Python (FastAPI + WebSocket) | None (browser-only) |
| **Frontend** | Vanilla JS + Three.js | Separate frontend | Next.js + Three.js |
| **Desktop App** | Tauri (planned) | Desktop client | Tauri |
| **Core Strength** | Agent intelligence + lip sync | TTS/STT variety + offline | VRM rendering + XR |

**Key Finding:** Amalgam is the strongest in agent intelligence (MCP, planning, reflection, memory) and lip sync quality, but lags in TTS/STT provider variety, documentation, and desktop app maturity.

---

## 2. Open-LLM-VTuber Analysis

### 2.1 Architecture

```
┌─────────────────────────────────────────────┐
│  Frontend (Live2D via pixi-live2d-display)   │
├─────────────────────────────────────────────┤
│  WebSocket (FastAPI)                         │
├──────────┬──────────┬───────────────────────┤
│ Agent    │ TTS Mgr  │ Conversation Handler  │
│ (LLM)   │ (ordered │ (single + group)       │
│          │  delivery)│                       │
├──────────┴──────────┴───────────────────────┤
│  ASR │ TTS │ MCP │ Memory │ Translation     │
│  (7)  │(20+)│     │        │                 │
└─────────────────────────────────────────────┘
```

- **Language:** Python backend, separate frontend
- **Config:** YAML files (per-character config alternates)
- **Communication:** WebSocket with typed messages

### 2.2 Features

**Voice Pipeline (Strongest Area):**
- **ASR (7 providers):** Azure, Faster Whisper, FunASR, Groq Whisper, OpenAI Whisper, Sherpa-ONNX, Whisper.cpp
- **TTS (20+ providers):** Azure, Bark, Cartesia, Coqui, CosyVoice/CosyVoice2, Edge TTS, ElevenLabs, Fish API, GPT-SoVITS, Melo TTS, MiniMax, OpenAI, Piper, pyttsx3, Sherpa-ONNX, SiliconFlow, Spark TTS, xTTS
- **VAD:** Silero VAD
- **Key optimization:** "Faster first response" — speaks as soon as the first sentence comma is detected, reducing perceived latency
- **Sentence segmentation:** regex or pysbd (PySBD is a professional sentence boundary detector)
- **TTS Task Manager:** Parallel TTS generation with ordered delivery via sequence counters

**LLM Providers (10+):**
- OpenAI compatible, Llama.cpp, Claude, Ollama, OpenAI, Gemini, Zhipu, DeepSeek, Groq, Mistral, LM Studio

**Agent Types:**
- `basic_memory_agent` — standard chat with memory
- `letta_agent` — integrates with Letta (formerly MemGPT) for persistent memory
- `hume_ai_agent` — integrates Hume AI for emotional expression

**Unique Features:**
- **Group conversation** — multiple AI participants in one chat (with human_name, character_name)
- **Desktop pet mode** — transparent background, AI companion floats on screen
- **Bilibili live streaming** — AI can stream on Bilibili
- **Translation** — DeepLX and Tencent translation integration
- **Think tag prompt** — LLMs without thinking output can show inner thoughts
- **Proactive speaking** — AI can initiate conversation
- **MCP Plus** — full MCP client with server registry and tool caching
- **i18n** — English, Chinese, Korean, Japanese

**MCP Support:**
- Full MCP client with `ServerRegistry`, `MCPClient`, `ToolAdapter`, `ToolExecutor`
- Stdio transport with persistent connections
- Tool result caching
- Multiple server management

### 2.3 What's Better Than Amalgam

| Area | Open-LLM-VTuber | Amalgam |
|------|-----------------|---------|
| TTS providers | 20+ | ~12 |
| ASR providers | 7 | ~6 |
| Group conversation | Yes | No |
| Desktop pet mode | Yes | No |
| Translation | DeepLX + Tencent | No |
| Letta/MemGPT integration | Yes | No |
| Hume AI integration | Yes | No |
| Bilibili streaming | Yes | No |
| Faster first response | Optimized | Basic |
| Sentence segmentation | pysbd option | None |
| TTS parallel generation | Ordered queue | Sequential |

### 2.4 What's Worse Than Amalgam

| Area | Open-LLM-VTuber | Amalgam |
|------|-----------------|---------|
| Avatar type | Live2D only | VRM (3D) |
| Lip sync | Basic Live2D | Advanced formant-based |
| Agent intelligence | Basic | Planning + Reflective |
| Memory system | Basic | Episodic + Semantic + Hybrid |
| MCP depth | Basic client | 10 pre-configured servers |
| Skill creation | No | Auto-skill from traces |
| Companion mode | No | Yes |
| Settings UI | YAML files | Full settings panel |
| Plugin system | No | Yes |
| Metrics/analytics | No | Yes |
| Desktop app | Separate client | Tauri integration |
| Documentation | Basic README | Moderate |

---

## 3. amica Analysis

### 3.1 Architecture

```
┌─────────────────────────────────────────────┐
│  Next.js (React/TypeScript)                  │
├─────────────────────────────────────────────┤
│  Three.js + @pixiv/three-vrm                 │
│  ├── VRM Viewer (Model, Room)                │
│  ├── EmoteController (ExpressionController)  │
│  ├── LipSync (AudioContext analysis)         │
│  ├── ProceduralAnimation                     │
│  └── XR Support (VR controllers, hands)      │
├─────────────────────────────────────────────┤
│  Chat System │ Voice System │ Vision System  │
│  (OpenAI,    │ (Piper,      │ (OpenAI,       │
│   Ollama,    │  ElevenLabs, │  LLaVA,        │
│   etc.)      │  etc.)       │  BakLLaVA)     │
├─────────────────────────────────────────────┤
│  Amica Life │ Function Calling │ Plugins     │
│  (autonomous│ (event-driven)   │ (news, etc.) │
│   behavior) │                  │              │
└─────────────────────────────────────────────┘
```

- **Language:** TypeScript/React (Next.js)
- **Config:** `.env.local` + `config.ts` defaults
- **Communication:** HTTP fetch (no WebSocket)
- **Desktop:** Tauri

### 3.2 Features

**VRM Rendering (Strongest Area):**
- Three.js + @pixiv/three-vrm
- MToonMaterial with 6 material type options (mtoon, mtoon_node, meshtoon, basic, depth, normal)
- WebGPU support (experimental)
- OrbitControls for camera
- XR support foundation (VR controllers, hand tracking) — temporarily disabled
- BVH (Bounding Volume Hierarchy) for accelerated raycasting
- Texture optimization utilities
- GLTF analysis and optimization
- Transparency optimization
- Drag-and-drop VRM loading
- VRM store with IndexedDB persistence

**Lip Sync:**
- AudioContext-based with AnalyserNode
- Time domain data analysis
- Sigmoid curve volume calculation
- Simple but effective mouth open value (0-1)

**Animation:**
- VRM animation files (.vrma): idle, dance, greeting, peace sign, shoot, spin, squat, etc.
- Mixamo animation support
- Procedural animation (breathing, subtle body movement via sine waves)
- Expression controller with preset emotions
- Auto-blink
- Auto look-at (gaze tracking)

**Emotion System (14 emotions):**
- neutral, happy, angry, sad, relaxed, surprised, shy, jealous, bored, serious, suspicious, victory, sleep, love
- LLM-generated emotion tags in response text
- System prompt designed to trigger expressions

**Amica Life (Autonomous Behavior):**
- Event-driven idle behavior system
- Queue-based event processing
- Idle text prompts
- Sleep/wake states
- Subconscious logging

**TTS Providers (10):**
- Piper, OpenAI TTS, ElevenLabs, SpeechT5, Coqui Local, AllTalk, Kokoro, RVC, Moshi, LocalXTTS

**STT Providers (3):**
- Whisper (browser), Whisper.cpp, OpenAI Whisper

**LLM Providers (8):**
- OpenAI, Llama.cpp, Ollama, KoboldAI, Window.ai, OpenRouter, Moshi, Echo

**Other Features:**
- Wake word detection
- Mid-phrase interrupt
- Chat mode (minimized avatar corner)
- Plugin system (function calling)
- Social media integration (Telegram, Twitter)
- External API
- Vision (camera-based image recognition)
- Extensive documentation site

### 3.3 What's Better Than Amalgam

| Area | amica | Amalgam |
|------|-------|---------|
| VRM material options | 6 types | Default only |
| XR/VR support | Foundation exists | No |
| Tauri desktop app | Working | Planned |
| VRM animations | 9 pre-built | Basic idle only |
| Social media | Telegram + Twitter | Telegram only |
| Documentation | Full docs site | README only |
| Drag-and-drop VRM | Yes | No |
| Procedural animation | Yes (breathing) | No |
| Browser-only mode | Yes | No |
| VRM store (IndexedDB) | Yes | No |
| Amica Life | Autonomous behavior | Basic idle |

### 3.4 What's Worse Than Amalgam

| Area | amica | Amalgam |
|------|-------|---------|
| MCP support | None | 10 servers |
| Tool calling | Basic function calling | Full MCP + local tools |
| Memory system | None | Episodic + Semantic + Hybrid |
| Agent intelligence | None | Planning + Reflective |
| Lip sync | Volume-based | Formant estimation + coarticulation |
| Emotion count | 14 | 24 |
| LLM providers | 8 | 17+ |
| Settings UI | .env.local only | Full settings panel |
| Session management | Load/save .txt | Full session history |
| Companion mode | No | Yes |
| WebSocket | No | Yes (with heartbeat) |
| Idle behavior | Basic | Advanced (3 states + micro-anims) |
| Saccadic eye movement | No | Yes |
| Plugin architecture | Basic | Full registry |
| Metrics/analytics | No | Yes |

---

## 4. Amalgam Current State

### 4.1 Architecture

```
┌─────────────────────────────────────────────┐
│  Vanilla JS Frontend + Three.js              │
│  ├── AvatarRenderer (VRM)                    │
│  ├── AdaptiveLipsyncManager                  │
│  ├── AdvancedLipSync (formant + coartic)     │
│  ├── IdleManager (3 states)                  │
│  └── SpriteAvatar mode                       │
├─────────────────────────────────────────────┤
│  WebSocket (with heartbeat + reconnect)      │
├─────────────────────────────────────────────┤
│  Python Backend (FastAPI)                    │
│  ├── Agent System                            │
│  │   ├── BasicAgent (tool-calling loop)      │
│  │   ├── ReflectiveAgent (auto-skill)        │
│  │   └── PlanningAgent (task decomposition)  │
│  ├── Memory (episodic/semantic/hybrid)       │
│  ├── MCP Client (10 servers)                 │
│  ├── Plugin System                           │
│  └── Settings (hot-reload + profiles)        │
└─────────────────────────────────────────────┘
```

### 4.2 Strengths

1. **Advanced Lip Sync** — Formant estimation with coarticulation smoothing and ARPAbet phoneme mapping. The best among all three projects.
2. **Agent Intelligence** — Three agent types (Basic, Reflective, Planning) with auto-skill creation from conversation traces.
3. **MCP Ecosystem** — 10 pre-configured MCP servers (shell, screenshot, puppeteer, obsidian, duckduckgo, etc.)
4. **Memory System** — Episodic (ChromaDB), semantic (BM25), hybrid strategies, compaction, fact extraction.
5. **Emotion System** — 24 emotions with VRM expression mapping and fallback candidates.
6. **Companion Mode** — Proactive behavior with idle/sleep states and micro-animations.
7. **Settings UI** — Full settings panel with tabs, dynamic fields, and hot-reload.
8. **Session Management** — Full conversation history with search and deletion.

### 4.3 Weaknesses

1. **TTS/STT Variety** — Fewer providers than Open-LLM-VTuber.
2. **Documentation** — Minimal compared to amica's docs site.
3. **Desktop App** — Tauri not yet integrated.
4. **VRM Animations** — Limited pre-built animations.
5. **Group Conversation** — Not supported.
6. **Translation** — Not supported.
7. **XR/VR** — No foundation.
8. **Procedural Animation** — No breathing/subtle body movement.
9. **Drag-and-Drop VRM** — Not supported.
10. **Browser-Only Mode** — Requires backend server.

---

## 5. Feature Comparison Matrix

| Feature | Amalgam | Open-LLM-VTuber | amica |
|---------|---------|-----------------|-------|
| **VRM Rendering** | Yes (Three.js + three-vrm) | No (Live2D only) | Yes (Three.js + three-vrm) |
| **Live2D Rendering** | No | Yes (pixi-live2d-display) | No |
| **Lip Sync Quality** | ★★★★★ Formant + coarticulation | ★★☆ Basic Live2D | ★★★ Volume-based sigmoid |
| **Idle Animation** | ★★★★★ 3 states + micro-anims | ★★★ Live2D motions | ★★★★ Procedural + VRMA |
| **Saccadic Eye Movement** | Yes | No | No |
| **Auto-Blink** | Yes (configurable) | Yes | Yes |
| **Gaze Tracking** | Head position tracking | Live2D lookAt | Auto look-at |
| **VRM Material Options** | Default only | N/A | 6 types (mtoon, basic, etc.) |
| **XR/VR Support** | No | No | Foundation (disabled) |
| **TTS Providers** | ~12 (Edge, ElevenLabs, OpenAI, AllTalk, Piper, Coqui, Kokoro, Azure, Dashscope, Volcengine, Deepgram, RVC) | 20+ (Azure, Bark, Cartesia, Coqui, CosyVoice, Edge, ElevenLabs, Fish, GPT-SoVITS, Melo, MiniMax, OpenAI, Piper, pyttsx3, Sherpa, SiliconFlow, Spark, xTTS) | ~10 (Piper, OpenAI, ElevenLabs, SpeechT5, Coqui, AllTalk, Kokoro, RVC, Moshi, LocalXTTS) |
| **STT Providers** | ~6 (Browser, Faster Whisper, OpenAI Whisper, Groq Whisper, Whisper.cpp, Deepgram, Sherpa) | 7 (Azure, Faster Whisper, FunASR, Groq Whisper, OpenAI Whisper, Sherpa, Whisper.cpp) | ~3 (Browser Whisper, Whisper.cpp, OpenAI Whisper) |
| **VAD** | Backend energy-based | Silero VAD | Silero VAD |
| **LLM Providers** | 17+ (Gemini, OpenRouter, ZAI, SiliconFlow, Groq, ChatGPT, Claude, LlamaCpp, KoboldAI, DeepSeek, Mistral, Together, Azure, Alibaba, HuggingFace, AWS, GCP) | 10+ (OpenAI, Llama.cpp, Claude, Ollama, Gemini, Zhipu, DeepSeek, Groq, Mistral, LM Studio) | ~8 (OpenAI, Llama.cpp, Ollama, KoboldAI, Window.ai, OpenRouter, Moshi, Echo) |
| **Tool Use** | Yes (MCP + local tools) | Yes (MCP Plus) | Basic function calling |
| **MCP Support** | ★★★★★ 10 pre-configured servers | ★★★ Basic MCP client | ☆ None |
| **Memory/Context** | ★★★★★ Episodic + Semantic + Hybrid + Compaction | ★★★ Basic memory agent | ☆ None (conversation only) |
| **Agent Types** | ★★★★★ Basic + Reflective + Planning | ★★★ Basic + Letta + Hume | ☆ None |
| **Auto-Skill Creation** | Yes (from conversation traces) | No | No |
| **Companion Mode** | Yes (proactive + idle/sleep) | Proactive speaking | Amica Life (autonomous) |
| **Multi-Language** | i18n (en, etc.) | i18n (en, zh, ko, ja) | Language config |
| **Offline Capable** | Partial (local LLM/TTS) | Yes (full offline mode) | Partial (browser STT) |
| **Mobile Support** | Responsive UI | Responsive UI | Responsive (Next.js) |
| **WebSocket** | Yes (heartbeat + reconnect) | Yes | No (HTTP fetch) |
| **REST API** | Yes (settings, memory, MCP) | Yes | Limited |
| **Settings UI** | ★★★★★ Full panel with tabs | ☆ YAML files | ☆ .env.local only |
| **History/Sessions** | ★★★★★ Full session management | ★★★ Chat history persistence | ★★ Load/save .txt |
| **Background Tasks** | Yes (async skill creation, reflection) | No | Yes (Amica Life events) |
| **Push Notifications** | No | No | No |
| **Group Conversation** | No | Yes (multi-AI) | No |
| **Translation** | No | Yes (DeepLX + Tencent) | No |
| **Desktop Pet Mode** | No | Yes (transparent bg) | No |
| **Desktop App** | Tauri (planned) | Separate client | Tauri (working) |
| **Plugin System** | Yes (registry + hooks) | No | Basic function calling |
| **Metrics/Analytics** | Yes (MetricsCollector) | No | No |
| **Telegram Bot** | Yes | No | Yes |
| **Social Media** | No | Bilibili streaming | Telegram + Twitter |
| **Vision/Camera** | No | Yes | Yes |
| **Wake Word** | Yes (openWakeWord) | No | Yes |
| **Drag-and-Drop VRM** | No | N/A | Yes |
| **VRM Animations** | Idle loop | Live2D motions | 9 VRMA files |
| **Procedural Animation** | No | No | Yes (breathing) |
| **Sprite Avatar** | Yes | No | No |
| **Profile System** | Yes (settings profiles) | No | No |
| **Hot-Reload Settings** | Yes (file watcher) | No | No |
| **Privacy Controls** | Yes (metrics opt-out, local-only) | No | No |
| **Shell Execution** | Yes (safe mode) | No | No |
| **Obsidian Integration** | Yes (MCP vault) | No | No |

---

## 6. Recommendations

### 6.1 STEAL — Features the Others Do Better

| Priority | Feature | Source | Effort | Impact |
|----------|---------|--------|--------|--------|
| 🔴 High | **More TTS providers** (Bark, CosyVoice, GPT-SoVITS, Melo TTS, Spark TTS) | Open-LLM-VTuber | Medium | High — more voice options = broader audience |
| 🔴 High | **Procedural breathing animation** | amica | Low | High — makes avatar feel alive |
| 🔴 High | **VRM drag-and-drop loading** | amica | Low | Medium — better UX for avatar customization |
| 🟡 Medium | **Group conversation** | Open-LLM-VTuber | High | Medium — unique differentiator |
| 🟡 Medium | **Translation support** (DeepLX) | Open-LLM-VTuber | Low | Medium — multilingual users |
| 🟡 Medium | **Desktop pet mode** (transparent background) | Open-LLM-VTuber | Medium | Medium — companion use case |
| 🟡 Medium | **VRM material type options** | amica | Low | Low — power user feature |
| 🟢 Low | **Social media integration** (Twitter) | amica | Medium | Low — niche use case |
| 🟢 Low | **XR/VR foundation** | amica | High | Low — future-proofing |
| 🟢 Low | **Full docs site** | amica | Medium | Medium — developer adoption |

### 6.2 IMPROVE — Features Amalgam Has But Could Be Better

| Priority | Feature | Current State | Improvement |
|----------|---------|---------------|-------------|
| 🔴 High | **TTS queue** | Sequential playback | Implement Open-LLM-VTuber's parallel generation with ordered delivery |
| 🔴 High | **VRM animations** | Basic idle loop | Add greeting, wave, nod, dance animations (like amica's 9 VRMA files) |
| 🟡 Medium | **Emotion system** | 24 emotions, good mapping | Add LLM-generated emotion tags parsing (like amica's `[emotion]` syntax) |
| 🟡 Medium | **Memory system** | Full but complex | Add Letta/MemGPT integration option (like Open-LLM-VTuber) |
| 🟡 Medium | **Browser STT** | Basic SpeechRecognition | Add Silero VAD for better voice activity detection |
| 🟢 Low | **i18n** | English + partial | Add Chinese, Korean, Japanese (like Open-LLM-VTuber) |
| 🟢 Low | **Settings UI** | Good but could be more polished | Add setup wizard (amica has introduction flow) |

### 6.3 INNOVATE — Features Unique to Amalgam or Missing in All Three

| Priority | Feature | Why It Matters |
|----------|---------|----------------|
| 🔴 High | **Advanced lip sync** (formant + coarticulation) | Already best-in-class. Market this. Consider open-sourcing the lip sync module. |
| 🔴 High | **Reflective agent + auto-skill** | No other project does this. Unique selling point for power users. |
| 🟡 Medium | **MCP ecosystem** (10 servers) | Deepest tool integration of any project. Add more servers (weather, calendar, Spotify). |
| 🟡 Medium | **Memory compaction + strategies** | Most sophisticated memory system. Add visualization of memory graph. |
| 🟡 Medium | **Plugin system with hooks** | Most extensible architecture. Build a plugin marketplace. |
| 🟢 Low | **Metrics dashboard** | No other project tracks conversation quality metrics. Build a visualization. |
| 🟢 Low | **Vault/Obsidian integration** | Unique knowledge management feature. Expand to Notion, Logseq. |
| 🟢 Low | **Sprite avatar mode** | Unique lightweight alternative to VRM. Good for low-end devices. |

### 6.4 DROP — Features Not Worth Maintaining

| Feature | Reason |
|---------|--------|
| **pyttsx3 TTS** | Low quality, platform-dependent, not worth supporting |
| **Some rarely-used LLM providers** | Focus on top 10 most-used providers |
| **Legacy emotion regex patterns** | Clean up the `_LEGACY_EMOTION_RE`, `_LEGACY_EXPRESSION_RE`, `_LEGACY_ACTION_RE` in `core.py` — they add complexity for backward compatibility with an old format |
| **Overly complex DEFAULTS dict** | The 400+ line defaults in settings.py could be split into modular config files |

---

## 7. Priority Roadmap

Top 10 features ranked by **Impact × (1 / Difficulty) × Uniqueness**:

### Rank 1: Procedural Breathing Animation
- **Impact:** High — avatar feels alive even when idle
- **Difficulty:** Low — ~50 lines of sine-wave bone rotation (copy from amica)
- **Uniqueness:** Common in amica, missing in Amalgam
- **Effort:** 1-2 hours
- **Details:** Add subtle spine/neck oscillation using `Math.sin(elapsedTime)` on VRM humanoid bones

### Rank 2: VRM Drag-and-Drop Loading
- **Impact:** High — users can instantly try new avatars
- **Difficulty:** Low — canvas drop event + GLTFLoader
- **Uniqueness:** Common in amica, missing in Amalgam
- **Effort:** 2-4 hours
- **Details:** Listen for `dragover`/`drop` on canvas, validate `.vrm` extension, load via existing GLTFLoader

### Rank 3: More TTS Providers (Bark, CosyVoice, MeloTTS)
- **Impact:** High — more voice variety for different languages/personalities
- **Difficulty:** Medium — each provider is a new module
- **Uniqueness:** Open-LLM-VTuber has 20+, Amalgam has ~12
- **Effort:** 1-2 days per provider
- **Details:** Start with Bark (local, multilingual) and CosyVoice (Chinese excellence)

### Rank 4: VRM Animation Library
- **Impact:** High — avatar can express through movement, not just face
- **Difficulty:** Medium — need VRMA files and animation mixer logic
- **Uniqueness:** amica has 9 animations, Amalgam has 1
- **Effort:** 1-2 days
- **Details:** Add greeting, wave, nod, thinking, excited animations. amica has free VRMA files in `public/animations/`

### Rank 5: Parallel TTS Generation with Ordered Delivery
- **Impact:** Medium-High — reduces perceived latency significantly
- **Difficulty:** Medium — async task queue with sequence counters
- **Uniqueness:** Open-LLM-VTuber's `TTSTaskManager` is elegant
- **Effort:** 1-2 days
- **Details:** Generate TTS for sentence N+1 while playing sentence N, deliver in order

### Rank 6: Translation Support (DeepLX)
- **Impact:** Medium — enables cross-language conversations
- **Difficulty:** Low — DeepLX is a simple HTTP API
- **Uniqueness:** Only Open-LLM-VTuber has this
- **Effort:** 4-6 hours
- **Details:** Add DeepLX as a middleware step in the response pipeline

### Rank 7: Desktop Pet Mode
- **Impact:** Medium — unique companion use case
- **Difficulty:** Medium — needs transparent window + always-on-top
- **Uniqueness:** Only Open-LLM-VTuber has this
- **Effort:** 2-3 days
- **Details:** Tauri supports transparent windows. Add a `--pet` flag that sets `decorations: false`, `transparent: true`, `alwaysOnTop: true`

### Rank 8: Enhanced Documentation Site
- **Impact:** Medium — developer adoption and user onboarding
- **Difficulty:** Medium — writing + hosting
- **Uniqueness:** amica has a full docs site, Amalgam has README
- **Effort:** 3-5 days
- **Details:** Use VitePress or Docusaurus. Sections: Quick Start, Configuration, MCP Guide, Agent System, API Reference

### Rank 9: Vision/Camera Integration
- **Impact:** Medium — avatar can "see" the user and surroundings
- **Difficulty:** High — needs camera API + vision LLM integration
- **Uniqueness:** Both Open-LLM-VTuber and amica have this
- **Effort:** 3-5 days
- **Details:** Add camera capture → base64 → vision LLM (GPT-4V, LLaVA) pipeline

### Rank 10: Memory Graph Visualization
- **Impact:** Low-Medium — unique insight into agent's knowledge
- **Difficulty:** Medium — D3.js or force-directed graph
- **Uniqueness:** No project has this
- **Effort:** 2-3 days
- **Details:** Visualize episodic/semantic memory as an interactive graph in the settings panel

---

## Appendix A: Technology Stack Comparison

| Component | Amalgam | Open-LLM-VTuber | amica |
|-----------|---------|-----------------|-------|
| Backend language | Python | Python | TypeScript (browser) |
| Backend framework | FastAPI | FastAPI | None |
| Frontend language | Vanilla JS | Separate | TypeScript (React) |
| Frontend framework | None (vanilla) | Unknown | Next.js |
| 3D rendering | Three.js | pixi-live2d-display | Three.js |
| Avatar format | VRM | Live2D | VRM |
| VRM library | @pixiv/three-vrm | N/A | @pixiv/three-vrm |
| Desktop app | Tauri (planned) | Separate client | Tauri |
| Config format | JSON | YAML | .env.local |
| State management | Module-level getters/setters | Service context | React Context |
| Build tool | Vanilla (ES modules) | Unknown | Vite + Next.js |
| Package manager | None (vanilla) | pip/conda | npm |

## Appendix B: Agent Architecture Comparison

### Amalgam Agent Hierarchy
```
BaseAgent (abstract)
├── BasicAgent (tool-calling loop, 5 iterations max)
├── ReflectiveAgent (wraps any agent, adds background learning)
│   ├── Auto-skill creation from complex traces
│   └── Periodic conversation quality reflection
└── PlanningAgent (task decomposition for compound requests)
    ├── Simple → delegates to BasicAgent
    └── Compound → decompose → execute steps → synthesize
```

### Open-LLM-VTuber Agent Types
```
basic_memory_agent (standard chat + memory)
letta_agent (MemGPT integration)
hume_ai_agent (Hume AI emotional expression)
```

### amica Agent Types
```
None — just chat backends (OpenAI, Ollama, etc.)
```

**Verdict:** Amalgam has the most sophisticated agent architecture by far.

## Appendix C: Lip Sync Quality Comparison

### Amalgam (Best)
- **Formant estimation:** FFT-based frequency analysis across 4 formant ranges (F1-F4)
- **Phoneme mapping:** ARPAbet phoneme → viseme mapping (39 phonemes → 13 visemes)
- **Coarticulation:** Majority vote with recency bias over sliding window
- **Viseme openness:** 13 viseme types with specific openness values
- **Fallback:** Frequency-based analysis when formant estimation unavailable

### amica (Good)
- **Volume-based:** AnalyserNode time domain data → max absolute volume
- **Sigmoid curve:** `1 / (1 + exp(-45 * volume + 5))` for natural falloff
- **Threshold:** Below 0.1 = silent
- **Result:** Single `mouthOpen` value (0-1)

### Open-LLM-VTuber (Basic)
- **Live2D expression:** Handled by Live2D SDK's built-in lip sync
- **No custom implementation:** Relies on pixi-live2d-display's default behavior

---

*Report generated by Jcode Agent on 2026-06-20*
