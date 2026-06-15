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
│   │   │   ├── interface.py         # Shared agent interface
│   │   │   ├── permissions.py       # Tool permission gating
│   │   │   ├── hooks.py             # Plugin hooks integration
│   │   │   ├── analytics.py         # Tool usage analytics
│   │   │   └── stream_processor.py  # Streaming response processor
│   │   ├── config/
│   │   │   ├── settings.py      # Persistent settings manager (JSON)
│   │   │   ├── schema.py        # Pydantic config schemas
│   │   │   └── character_schema.py
│   │   ├── context/
│   │   │   ├── builder.py       # Context builder (Jinja2 template)
│   │   │   ├── budgets.py       # Token budget management
│   │   │   ├── vault_injector.py# Vault context injection
│   │   │   └── templates/       # Jinja2 templates
│   │   ├── llm/
│   │   │   ├── litellm_provider.py  # Unified LiteLLM wrapper
│   │   │   ├── router.py           # Provider routing
│   │   │   └── cost_router.py      # Cost-aware provider selection
│   │   ├── memory/
│   │   │   ├── manager.py       # Memory orchestrator (5 tiers)
│   │   │   ├── working.py       # In-memory ring buffer (last 20 turns)
│   │   │   ├── episodic.py      # Per-session semantic storage (ChromaDB)
│   │   │   ├── semantic.py      # Cross-session facts (BM25)
│   │   │   ├── hybrid.py        # BM25 + vector fusion
│   │   │   ├── fts.py           # Full-text keyword search (FTS5)
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
│   │   ├── context_builder.py    # ContextBuilder (legacy, see context/)
│   │   ├── user_profile.py       # Persistent user profiling
│   │   ├── metrics.py            # MetricsCollector + cost estimation
│   │   ├── memory.py             # Memory (legacy, see memory/)
│   │   ├── relationship.py       # Per-character relationship tracking
│   │   ├── vault.py              # Markdown vault manager
│   │   ├── startup.py            # Shared application init + shutdown
│   │   ├── log_config.py         # structlog configuration
│   │   ├── paths.py              # Centralized path definitions
│   │   └── deps.py               # Singleton dependencies
│   ├── mcp/
│   │   ├── client.py             # MCP stdio client
│   │   └── servers/              # Tool servers (shell, filesystem, etc.)
│   ├── plugins/
│   │   ├── base.py               # BasePlugin abstract class
│   │   ├── manager.py            # PluginManager — discovery, lifecycle
│   │   └── example_plugin.py     # Reference implementation
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
├── AUDIT.md                      # Security & correctness audit
├── amalgam-review-v2.md          # Comprehensive architecture review
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
- **5-Tier Memory**: Working → Episodic → Semantic → Hybrid → FTS. Graceful degradation if ChromaDB unavailable.
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
    → backend/core/memory/  (5-tier memory)
    → backend/core/context/ (Jinja2 template builder)
    → backend/core/metacognitive/ (strategy selection)
    → backend/core/self_learning/ (auto skills, corrections)
    → backend/core/user_profile.py
    → backend/core/metrics.py
    → backend/plugins/      (PluginManager)
```
Each subsystem is independently testable with isolated dependencies.
