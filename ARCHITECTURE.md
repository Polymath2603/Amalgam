# Codebase Architecture

## Directory Tree
```
k/
├── backend/
│   ├── app.py                   # FastAPI app factory, lifespan, rate limiting, /health
│   ├── api/
│   │   ├── deps.py              # Depends() — shared component injection
│   │   ├── telegram.py          # Telegram bot interface
│   │   ├── ws/
│   │   │   ├── handler.py       # WebSocket chat handler (ChatSession)
│   │   │   └── tts_service.py   # TTS synthesis + sentence streaming
│   │   └── routes/
│   │       ├── settings.py      # GET/POST /api/settings
│   │       ├── characters.py    # GET /api/characters, animations
│   │       ├── push.py          # Push notification token registration
│   │       ├── memory.py        # sessions, facts, clear
│   │       ├── vault.py         # Vault CRUD + search
│   │       ├── relationship.py  # Relationship status
│   │       ├── metrics.py       # Usage metrics
│   │       ├── commands.py      # Slash commands endpoint
│   │       ├── tts.py           # TTS synthesis endpoint
│   │       └── mcp.py           # MCP tool listing
│   ├── core/
│   │   ├── agent/
│   │   │   ├── base.py              # BaseAgent ABC + AgentTrace dataclass
│   │   │   ├── basic_agent.py       # Stateless tool-calling loop
│   │   │   ├── reflective_agent.py  # Wraps BasicAgent + periodic reflection
│   │   │   ├── planning_agent.py    # Task decomposition → steps → synthesis
│   │   │   ├── core.py              # Legacy monolithic Agent (backwards compat)
│   │   │   ├── factory.py           # AgentFactory — runtime agent selection
│   │   │   ├── permissions.py       # Tool permission gating
│   │   │   ├── hooks.py             # Plugin hooks integration
│   │   │   └── analytics.py         # Tool usage analytics
│   │   ├── config/
│   │   │   ├── settings.py          # Persistent settings manager (JSON)
│   │   │   └── character_schema.py  # Pydantic validation for character index.yaml
│   │   ├── context_builder.py    # ContextBuilder — Jinja2 templates as inline
│   │   │                         # strings (jinja2.BaseLoader), not template files
│   │   ├── llm/
│   │   │   ├── litellm_provider.py  # Unified LiteLLM wrapper
│   │   │   ├── router.py           # Provider routing
│   │   │   └── cost_router.py      # Cost-aware provider selection
│   │   ├── memory/
│   │   │   ├── manager.py       # Memory façade — ties working/episodic/semantic together
│   │   │   ├── working.py       # In-memory ring buffer (last 20 turns)
│   │   │   ├── episodic.py      # Per-session semantic storage (ChromaDB)
│   │   │   ├── semantic.py      # Cross-session facts (BM25)
│   │   │   ├── hybrid.py        # BM25 + vector fusion (retrieval, not a separate memory type)
│   │   │   ├── fts.py           # Full-text keyword search (FTS5) (retrieval, not a separate memory type)
│   │   │   ├── cache.py         # FACTCache — embedding dedup
│   │   │   ├── session_index.py # Fast session listing
│   │   │   └── consolidator.py  # Importance-based compaction
│   │   ├── metacognitive/
│   │   │   ├── engine.py            # MetaCognitiveEngine — orchestrator
│   │   │   ├── strategy_selector.py # Intent→LLM param mapping
│   │   │   ├── delta_evaluator.py   # Per-turn quality scoring
│   │   │   └── adaptation_engine.py # Rolling-window strategy adaptation
│   │   ├── self_learning/
│   │   │   ├── auto_skill.py     # AutoSkillCreator — SKILL.md generation
│   │   │   ├── corrections.py    # CorrectionStore — learns from user corrections
│   │   │   ├── improvement.py    # SkillImprover — periodic library review
│   │   │   └── preferences.py    # PreferenceLearner — behavioral inference
│   │   ├── user_profile.py       # Persistent user profiling — the "user model" partition
│   │   ├── metrics.py            # MetricsCollector + cost estimation
│   │   ├── relationship.py       # Per-character relationship tracking
│   │   ├── vault.py              # Markdown vault manager
│   │   ├── startup.py            # Shared application init + shutdown
│   │   ├── log_config.py         # structlog configuration
│   │   ├── paths.py              # Centralized path definitions
│   │   └── deps.py               # Singleton dependencies
│   ├── core/mcp/
│   │   └── client.py             # MCP client (separate from backend/mcp/servers/ below)
│   ├── core/plugins/
│   │   └── example_plugin.py     # Reference plugin implementation
│   ├── mcp/
│   │   └── servers/              # Tool servers (shell, filesystem, etc.)
│   ├── plugins/
│   │   ├── base.py               # BasePlugin abstract class
│   │   ├── manager.py            # PluginManager — discovery, lifecycle
│   │   └── emotion_analyzer/     # Built-in plugin
│   ├── voice/
│   │   ├── pipeline.py           # Voice capture → VAD → STT
│   │   ├── stt_configurator.py   # STT engine configuration
│   │   └── tts/                  # TTS providers (edge-tts, etc.)
│   └── tests/                    # Test suite (309+ tests)
├── webui/                        # Consolidated Frontend
│   ├── index.html                # Main SPA
│   ├── css/style.css             # Themes + Overlay styles
│   ├── js/                       # app.js, avatar.js, etc.
│   └── locales/                  # i18n (en, zh)
├── data/                         # Persistent user data
│   ├── characters/               # Character VRM models + configs
│   ├── conversations/            # Session storage (JSON)
│   └── settings.json             # User settings
├── ARCHITECTURE.md               # This file
└── requirements.txt              # Python dependencies
```

## Agent Architecture
```
BaseAgent (ABC)
  ├── BasicAgent      — Stateless tool-calling loop (stream_with_tools)
  ├── ReflectiveAgent — Wraps BasicAgent + periodic reflection (every 5 turns)
  │                     → updates UserProfile, creates skills, stores corrections
  └── PlanningAgent   — Task decomposition → step execution → synthesis
                        Simple tasks fast-path through BasicAgent

AgentFactory — Registry pattern for runtime selection via config
```

## Memory System (5-tier hierarchy)
| Tier | Module | Purpose | Latency |
|------|--------|---------|---------|
| **Working** | `memory.working` | In-memory ring buffer (last 20 turns) | ~0μs |
| **Episodic** | `memory.episodic` | Per-session semantic storage (ChromaDB) | ~1ms |
| **Semantic** | `memory.semantic` | Cross-session facts (BM25) | ~5ms |
| **Hybrid** | `memory.hybrid` | BM25 + vector fusion | ~10ms |
| **FTS** | `memory.fts` | Full-text keyword search (FTS5) | ~5ms |

Supporting: `FACTCache` (embedding dedup), `SessionIndex` (fast listing), `Consolidator` (importance-based compaction).

## Metacognitive Engine
```
StrategySelector (intent → LLM params: temperature, iterations, CoT)
       ↓
DeltaEvaluator (per-turn quality: response_time, coherence, relevance, tool_success, token_efficiency)
       ↓
AdaptationEngine (rolling-window avg → strategy: default/conservative/creative/precise)
       ↓
MetaCognitiveEngine (orchestrator: select → evaluate → adapt → record)
```

## Self-Learning Subsystem
| Module | Function |
|--------|----------|
| `AutoSkillCreator` | Detects ≥3 tool call turns, auto-generates SKILL.md |
| `CorrectionStore` | Regex-based correction detection + keyword relevance matching |
| `SkillImprover` | Periodic review: identifies stale/unused skills, pruning |
| `PreferenceLearner` | Behavioral inference: verbosity, engagement, response style |

## Communication Protocol
- **WebSocket** (`/ws/chat`): Bidirectional streaming. Signal tuples for emotions, expressions, tool calls, roleplay, permissions, errors.
- **REST API**: Settings, characters, memory, vault, push tokens, metrics.
- **Server-Sent**: `client_hello` / `server_hello` capability negotiation.

## Key Design Decisions
- **Modular Agent Architecture**: Pluggable agent types via `BaseAgent` ABC + factory pattern.
- **5-Partition Memory**: Working → Episodic → Semantic (with hybrid BM25+vector and FTS5 as retrieval mechanisms over it, not separate memory types) → Procedural (the skill system) → User model. Graceful degradation if ChromaDB unavailable.
- **Structured Logging**: `structlog` with JSON/console modes, idempotent init.
- **Rate Limiting**: Per-IP sliding window REST middleware (120 req/min).
- **Metrics**: SQLite-backed `MetricsCollector` with auto cost estimation (47 model entries).
- **Plugin System**: Auto-discovery from filesystem, async lifecycle, error isolation.
- **Push Notifications**: Token persistence to `data/push_tokens.json`.
- **Standardized Paths**: All paths via `backend.core.paths` (no hardcoded paths).
- **Atomic Writes**: Tempfile + fsync + os.replace for settings persistence.

## Async Consistency
| Module | Pattern |
|--------|---------|
| Memory | Hybrid (sync file I/O in executor + async wrappers) |
| Agent | Fully async generators |
| LLM | Fully async (LiteLLM) |
| Relationship | Fully async (aiosqlite + WAL mode) |
| Metrics | Fully async (aiosqlite) |
| Plugins | Async lifecycle hooks |
| UserProfile | Fully sync (small scope) |

## Dependency Flow
```
backend/api/ws/handler.py
  → backend/core/agent/    (BaseAgent, BasicAgent, etc.)
    → backend/core/llm/    (LiteLLMProvider, CostRouter)
    → backend/core/memory/  (working/episodic/semantic partitions)
    → backend/core/context_builder.py (Jinja2 templates, inline strings)
    → backend/core/metacognitive/ (strategy selection)
    → backend/core/self_learning/ (auto skills, corrections)
    → backend/core/user_profile.py
    → backend/core/metrics.py
    → backend/plugins/      (PluginManager)
```
Each subsystem is independently testable with isolated dependencies.
