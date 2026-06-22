# Wiring Analysis Report

**Generated:** 2026-06-22  
**Method:** Graphify (9,687 nodes, 17,313 edges) + manual import chain tracing  
**Commit:** `1050ea1`

---

## 🔴 Critical Wiring Issues (Must Fix)

### 1. `backend/api/telegram.py` — Built but NEVER wired
- **Problem:** Full Telegram bot integration exists (`TelegramBot` class, webhook handler, message routing) but `app.py` never imports or starts it.
- **Evidence:** Zero imports from `backend.api.telegram` anywhere.
- **Fix:** Needs to be wired in `app.py` startup as an `asyncio.create_task(bot.run())`.

### 2. `backend/plugins/` — Plugin manager loaded but plugins never executed
- **Problem:** `startup.py` creates a `PluginManager` and stores it in the shared dict, but the plugin lifecycle (init, register hooks, event dispatch) is never actually executed. The single existing plugin (`emotion_analyzer`) is never loaded.
- **Evidence:** `startup.py:73-76` creates PluginManager but `plugin_mgr.discover()` / `plugin_mgr.load_all()` are never called.
- **Fix:** Call `plugin_mgr.discover()` and `plugin_mgr.load_all()` in startup.

### 3. `backend/grpc/server.py` — gRPC server built but never started
- **Problem:** Complete gRPC agent service (`AgentService`, protobuf definitions, port 50051) but `app.py` never calls `serve_grpc()`.
- **Evidence:** Zero references in app.py or startup.py.
- **Fix:** Wire `serve_grpc()` as background task in startup.

### 4. `backend/core/permissions.py` vs `backend/core/agent/permissions.py` — TWO permission systems
- **Problem:** TWO entirely separate `PermissionGate` classes exist:
  - `backend/core/permissions.py` — **NEVER IMPORTED** by anything (dead code)
  - `backend/core/agent/permissions.py` — Used by MCP client, has `ToolPermissions` + `PermissionGate`
- **Evidence:** Only `backend.core.agent.permissions` is imported (by `mcp/client.py`).
- **Fix:** Remove `backend/core/permissions.py` or redirect to the real one.

---

## 🟡 High-Priority Wiring Mismatches

### 5. `deps.py` init ORDER is wrong — agent depends on MCP, but MCP not configured yet
- **Problem:** In `get_shared()`, agent is created at the END but depends on `mcp_client` which is initialized mid-list. More critically, `mcp_client.register_subagent_spawner(_shared["agent"].spawn_subagent)` is called AFTER agent creation — but this creates a circular dep where agent needs MCP and MCP needs agent.
- **Evidence:** Line `mcp_client.register_subagent_spawner(...)` is an after-the-fact fix for the circular dependency.

### 6. `backend/core/plugin.py` (old) vs `backend/plugins/` (new) — Two plugin abstractions
- **Problem:** Two plugin systems exist:
  - `backend.core.plugin` — Event-driven callback hooks. ACTIVE, used by agent/base.py, memory/manager.py.
  - `backend.plugins` — Class-based plugin system with PluginManager. Loaded but never activated.
- **Evidence:** Both systems coexist. `backend/plugins/base.py` imports from `backend.core.plugin`.
- **Severity:** Architectural confusion.

### 7. `backend/core/agent/interface.py` — Dead re-export shim
- **Problem:** Contains only `from backend.core.agent.base import BaseAgent, AgentTrace, ToolCall`. Exists only to not break old imports, but nothing imports from it.
- **Fix:** Remove it.

### 8. `backend/core/agent/stream_processor.py` — Never imported anywhere
- **Problem:** Contains `StreamProcessor` class — completely unused.
- **Evidence:** Zero imports across entire codebase.
- **Fix:** Remove or wire.

### 9. Self-learning modules — wired BUT with empty tool_calls
- **Problem:** AutoSkillCreator is now called but with `tool_calls=[]` (empty list). The comment says "tool_calls tracking not yet wired in this loop". So it runs but can never create a skill.
- **Evidence:** `handler.py:280`: `tool_calls=[]` with comment.
- **Fix:** Wire tool_call tracking in the agent loop.

### 10. Settings propagation — partial
- **Problem:** Only `llm.reload_settings()` and `agent().update_settings()` are called after batch settings save. TTS, STT, wake word, companion settings changes don't propagate to running instances.
- **Evidence:** `settings.py` routes only push to llm + agent.
- **Fix:** Need reload callbacks for all subsystems.

---

## 🟢 Watch Items

### 11. `backend/core/config/character_schema.py` — Not directly imported
- Characters loaded via `load_characters_from_yaml` in `startup.py`, which uses the YAML directly, not the schema validator.

### 12. `backend/scripts/generate-icons.py` — Standalone script
- Never called from app. `icon_generator.py` (in utils) IS called from startup.

### 13. `backend/voice/stt/utils.py` — Utility file never imported
- Contains STT helpers but nothing imports it.

### 14. `backend/voice/wakeword/` — Router exists but providers may not be dynamically loaded
- `WakeWordRouter` is created in deps.py but there's no provider class discovery (unlike TTS/STT which have `_PROVIDER_CLASSES`).

### 15. WebUI JS — All modules imported correctly
- All 16 modules in `webui/js/modules/` are imported by `app.js`. No dead JS modules.

### 16. Routes — ALL wired in app.py
- All 12 route modules (`settings`, `characters`, `commands`, `mcp`, `memory`, `push`, `vault`, `relationship`, `tts`, `setup`, `companion`, plus `ws/handler.py`) are imported and wired in `app.py`. The `__init__.py` being empty is fine — app.py imports by name.

---

## Summary

| Category | Count | Severity |
|----------|-------|----------|
| Built but NEVER wired | 3 (telegram, plugins, gRPC) | 🔴 Critical |
| Dead code (never imported) | 3 (permissions.py, interface.py, stream_processor.py) | 🟡 High |
| Wiring with wrong params | 1 (AutoSkillCreator gets empty tool_calls) | 🟡 High |
| Partial wiring | 3 (settings propagation, plugin activation, self-learning loop integration) | 🟡 High |
| Duplicate abstractions | 2 (permissions, plugin systems) | 🟡 High |
| Working correctly | ~40 modules | ✅ |

**Total wasted code:** ~3,000+ lines of built-but-never-used functionality (telegram bot, gRPC server, plugins, dead modules).
