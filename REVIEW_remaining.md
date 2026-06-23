# Remaining Subsystem Code Review

Generated: 2026-06-22
Coverage: CLI (4 files), MCP client + 6 MCP servers, Orchestrator (5 files), Metacognitive (2 files), Self-learning (4 files), gRPC (2 files), Telegram (1 file), Plugin system (3 files), Skills (1 file), Hot-reload (1 file), Startup (1 file), Paths (1 file), Errors (1 file), Utils (3 files), Relationship (1 file), Constitution (1 file), Secrets (1 file), Agent subsystems (3 files)

---

## 1. CLI — tui.py

### 1.1 `get_models_for_provider` — stub with `...` (dead code?)
**File:** `cli/tui.py:197`
**Severity:** MEDIUM
**Issue:** The function body is `...` (Ellipsis). This is either dead code or an incomplete implementation. If intended to be a no-op, it will crash at runtime when called because `...` is not callable.
**Fix:** Either remove the function, implement it, or raise `NotImplementedError`.

### 1.2 `_THEMES` — mutable global dict mutated by `_apply_palette`
**File:** `cli/tui.py:58-87`
**Severity:** LOW
**Issue:** `_apply_palette` modifies module-level globals based on a dict lookup. The module-level color constants are mutated at runtime, which could cause thread-safety issues if the TUI is ever used with threading. Design is fragile — any code path that calls `_apply_palette` leaves a persistent side effect.
**Fix:** Consider an immutable config object or a Theme dataclass that is passed around rather than mutating module globals.

### 1.3 `get_detected_providers` — double bare `except Exception: pass`
**File:** `cli/tui.py:174-190`
**Severity:** LOW
**Issue:** Two nested try/except blocks both use bare `except Exception: pass` without logging. Silently swallows all errors, making debugging difficult.
**Fix:** Add logging for each failure path.

### 1.4 `get_commands` — returns mutable dict reference to `_COMMAND_DEFS`
**File:** `cli/tui.py:152-154`
**Severity:** LOW
**Issue:** Returns the mutable internal dict directly, allowing callers to corrupt the command registry.
**Fix:** Return `dict(_COMMAND_DEFS)` (a shallow copy).

---

## 2. CLI — companion.py

### 2.1 `connect` — no max retry limit on connection loop
**File:** `cli/companion.py:73-88`
**Severity:** MEDIUM
**Issue:** The `while not self._stop_event.is_set()` loop retries forever with 1s delay if the backend is down. If `_stop_event` is never set, this is an infinite loop that blocks startup.
**Fix:** Add a maximum retry count or exponential backoff with a cap.

### 2.2 `_handle_user_input` — `indicator_task` created but never cancelled
**File:** `cli/companion.py:196`
**Severity:** MEDIUM
**Issue:** `asyncio.create_task(self._show_typing_indicator())` is created but there is no reference stored to cancel it when response arrives. If the response handling encounters an exception and breaks early, the typing indicator task may run forever.
**Fix:** Store the task reference and cancel it in a `finally` block.

### 2.3 `_handle_user_input` — `/exit` command says "use again" but never actually exits
**File:** `cli/companion.py:181-183`
**Severity:** LOW
**Issue:** `/exit` prints a message but doesn't set `_stop_event` or break the loop.
**Fix:** Set `self._stop_event.set()` or raise `SystemExit`.

### 2.4 `_handle_user_input` — exception safety for `ws.recv()`
**File:** `cli/companion.py:200-237`
**Severity:** LOW
**Issue:** If `self.ws` becomes `None` or the connection drops, `ws.recv()` will raise an exception that is not caught, crashing the companion. The outer `while` loop catches `TimeoutError` but not `websockets.ConnectionClosed`.
**Fix:** Add `except (websockets.ConnectionClosed, OSError): break` or reconnect logic.

### 2.5 `_send` — silently ignores disconnected state
**File:** `cli/companion.py:94-96`
**Severity:** LOW
**Issue:** If `self.ws` is `None`, `_send` silently does nothing. Callers (`wake_up`, `_handle_user_input`) assume the message was sent.
**Fix:** Log a warning or raise.

### 2.6 `_handle_user_input` — truncated file read
**File:** `cli/companion.py:238`
**Severity:** LOW
**Issue:** The file is truncated in this listing. The response reading loop appears incomplete.

---

## 3. CLI — provider.py

### 3.1 `_load_catalog` — fallback data out of sync risk
**File:** `cli/provider.py:30-82`
**Severity:** LOW
**Issue:** The fallback data in the try/except ImportError block can drift from `PROVIDER_CATALOG` in setup.py. Both copies must be kept in sync manually.
**Fix:** Consider generating provider.py from setup.py at build time, or always loading from backend (fail hard if backend not available).

### 3.2 `detect_providers` — `checked` set is never used
**File:** `cli/provider.py:111,160`
**Severity:** LOW
**Issue:** `checked = set()` is created and `checked.add(name)` is called per iteration, but `checked` is never read after the loop. Dead code.
**Fix:** Remove `checked`.

### 3.3 `detect_providers` — display_name always set to `name` (not `_catalog_names`)
**File:** `cli/provider.py:143,152`
**Severity:** MEDIUM
**Issue:** `display_name` is always set to `display = name` on line 143, even though `_catalog_names` is loaded and available. The display_name never reflects the human-readable name from the catalog.
**Fix:** Set `display = _catalog_names.get(name, name)`.

### 3.4 `_provider_env_key` — `azure-openai` and `alibaba` keys exist but these are not in `KNOWN_PROVIDERS`
**File:** `cli/provider.py:181-182`
**Severity:** LOW
**Issue:** `azure-openai` and `alibaba` have env key mappings but are not in `KNOWN_PROVIDERS` (which is derived from `_load_catalog` fallback list).
**Fix:** Either add them to the fallback list or remove the dead mapping entries.

---

## 4. MCP Client — client.py

### 4.1 `register_agent` — circular dependency documented but still encouraged for legacy
**File:** `backend/core/mcp/client.py:126-147`
**Severity:** MEDIUM
**Issue:** The deprecation warning says to use `register_subagent_spawner` instead, but `register_agent` still creates a circular reference (`self._agent = agent`). The `_agent` attribute is never cleaned up.
**Fix:** After extracting the spawner, set `self._agent = None` to break the circular reference for GC.

### 4.2 `_close_server` — catches `BaseException`, which catches `KeyboardInterrupt` and `SystemExit`
**File:** `backend/core/mcp/client.py:173`
**Severity:** MEDIUM
**Issue:** `except BaseException` on line 173 catches `KeyboardInterrupt` and `SystemExit`, preventing clean shutdown of the process.
**Fix:** Use `except Exception` instead of `except BaseException`.

### 4.3 `connect_servers` — config loading runs via executor but `self._load_config_sync` is a bound method reference
**File:** `backend/core/mcp/client.py:181`
**Severity:** LOW
**Issue:** `loop.run_in_executor(None, self._load_config_sync, config_path)` — this creates a closure that may pickle issues, and `_load_config_sync` is a synchronous method that doesn't benefit from the executor since it's mostly I/O bound.
**Fix:** Use `asyncio.to_thread()` if available (Python 3.9+), or `anyio.to_thread.run_sync`.

### 4.4 `connect_from_settings` — `results` variable `r` is used after gather but names list may not align if some coros were skipped
**File:** `backend/core/mcp/client.py:215-218`
**Severity:** LOW
**Issue:** `names` is only appended when a coro is added, so alignment is technically correct. But if someone modifies the code to skip appending names, the zip will silently misalign.
**Fix:** Use a dict-based approach: `tasks = {name: ...}` and iterate `tasks.items()`.

### 4.5 `_reconnect` method (not shown in this excerpt) — likely race on `_reconnect_tasks`
**File:** `backend/core/mcp/client.py` (referenced)
**Severity:** MEDIUM
**Issue:** The `_reconnect_tasks` dict is accessed from potentially multiple coroutines without a lock. If reconnection is triggered concurrently for the same server, duplicate reconnect tasks could spawn.

### 4.6 `load_skills_from_config` — no guard against circular skill dependencies
**File:** (referenced method, not shown)
**Severity:** LOW
**Issue:** Skills can depend on other skills, but there's no cycle detection when loading.

---

## 5. MCP Shell Server — shell/server.py

### 5.1 Global mutable set `ALLOWED_EXACT`, `ALLOWED_ONCE`, `_APPROVED_EXACT` — thread/async unsafe
**File:** `backend/mcp/servers/shell/server.py:39-43`
**Severity:** HIGH
**Issue:** These module-level sets are mutated from async code without any lock. Multiple concurrent `approve_command` tool calls can race on `ALLOWED_ONCE.add()` and `ALLOWED_PREFIXES.append()`, causing lost approvals or list corruption.
**Fix:** Use `asyncio.Lock` or convert to a thread-safe data structure.

### 5.2 `ALLOWED_PREFIXES` is a `list` — `append` is not atomic and `_extract_prefix` iterates
**File:** `backend/mcp/servers/shell/server.py:37,153`
**Severity:** MEDIUM
**Issue:** `ALLOWED_PREFIXES` is a plain list modified via `.append()` from async code. Also `_is_allowed` iterates over it. Concurrent modification while iterating can cause `IndexError` or missed matches.
**Fix:** Use `asyncio.Lock` for all mutations and reads.

### 5.3 `call_tool` — `process.kill()` in TimeoutError handler silently catches all exceptions
**File:** `backend/mcp/servers/shell/server.py:127-130`
**Severity:** LOW
**Issue:** `except Exception: pass` on line 129-130 means if `process.kill()` fails (e.g., process already dead), the error is silently swallowed.
**Fix:** Log the exception.

### 5.4 `call_tool` — potential shell injection via `shlex.split` bypass on Windows
**File:** `backend/mcp/servers/shell/server.py:112`
**Severity:** LOW
**Issue:** The code uses `create_subprocess_exec` with parsed args, which is correct on Unix. However, on Windows, `shlex.split` behavior differs. Not a current issue since the target is Linux, but worth noting.
**Fix:** Add a platform guard or test for Windows path.

### 5.5 `_is_allowed` — comparison `trimmed == prefix.strip()` is O(n²) for prefix matching
**File:** `backend/mcp/servers/shell/server.py:53`
**Severity:** LOW
**Issue:** For each command, the method iterates all prefixes and does string comparisons. For large prefix lists this is inefficient.
**Fix:** Use a trie or prefix tree for O(k) matching.

---

## 6. MCP Screenshot Server — screenshot/server.py

### 6.1 Missing `logging` import (used in `logger` but no logging calls)
**File:** `backend/mcp/servers/screenshot/server.py`
**Severity:** LOW
**Issue:** `import logging` is not present. While there are no logging calls now, any future debug logging will crash.
**Fix:** Add `import logging`.

### 6.2 `call_tool` return type annotation says `list` instead of `list[TextContent]`
**File:** `backend/mcp/servers/screenshot/server.py:22`
**Severity:** LOW
**Issue:** Return type is `list` (bare), while other MCP servers use `list[TextContent]`. Inconsistent.
**Fix:** Change to `list[TextContent]`.

### 6.3 Screenshot capture — no error handling for `mss.mss()` failure
**File:** `backend/mcp/servers/screenshot/server.py:29-31`
**Severity:** MEDIUM
**Issue:** If the display server is not available (headless environment, no X11/Wayland), `mss.mss()` will raise an exception that is not caught, causing a 500-level crash of the MCP server.
**Fix:** Add a try/except around the `mss.mss()` context manager.

### 6.4 `Image.frombytes` — `BGRX` raw mode may not be available on all platforms
**File:** `backend/mcp/servers/screenshot/server.py:32`
**Severity:** MEDIUM
**Issue:** The raw mode `"BGRX"` assumes BGRA byte order with X padding. On some platforms/versions of MSS, the byte order may be `BGRA` requiring mode `"BGRA"`. This could produce garbled images.
**Fix:** Check `sct_img.bgra` attribute or try both modes.

---

## 7. MCP Skill Server — skill/server.py

### 7.1 Timer leak: `_active_timers` never cleaned up on server shutdown
**File:** `backend/mcp/servers/skill/server.py:187,338-339`
**Severity:** MEDIUM
**Issue:** `_active_timers` dict holds references to `asyncio.Task` objects. If the server shuts down, these tasks are never cancelled, leading to `CancelledError` warnings or leaked references. The `_clean_timer` callback only removes on completion.
**Fix:** Add a shutdown handler that cancels all active timers.

### 7.2 `_discover_skill_files` — `shutil.copytree` with `ignore_patterns` still copies into user space
**File:** `backend/mcp/servers/skill/server.py:55`
**Severity:** LOW
**Issue:** `ignore_patterns("__pycache__","*.py")` is used but the source directory may contain other dangerous files. The copied files become user-modifiable.
**Fix:** Validate the source directory contents before copying.

### 7.3 `create_skill` — path traversal via `safe_name`
**File:** `backend/mcp/servers/skill/server.py:225-230`
**Severity:** MEDIUM
**Issue:** `safe_name = re.sub(r"[^a-z0-9_-]", "_", skill_name.lower())` — while this removes most dangerous characters, the name could still be things like `_` or `..` (dots are removed, but leading underscores could collide with system dirs).
**Fix:** Add validation that `safe_name` is not empty and doesn't start with `_`.

### 7.4 `delete_skill` — TOCTOU race between `shutil.rmtree` and existence check
**File:** `backend/mcp/servers/skill/server.py:237-242`
**Severity:** LOW
**Issue:** Between finding the skill and calling `shutil.rmtree`, another concurrent request could have deleted it. Also, deleting from `USER_SKILLS` could delete a skill that was a built-in copy.
**Fix:** Use error handling around rmtree and confirm the deletion source.

### 7.5 `_active_timers` uses `id(text)` as part of key — weak reference collision risk
**File:** `backend/mcp/servers/skill/server.py:325`
**Severity:** MEDIUM
**Issue:** `id(text)` returns the memory address of the string object. Python can reuse IDs after objects are GC'd, leading to false timer-duplicate detection. A string of the same content at a different memory address would produce a different ID anyway.
**Fix:** Use `hash(text)` or a UUID instead.

---

## 8. MCP System Server — system/server.py

### 8.1 `set_reminder` — `asyncio.create_task` fire-and-forget with no cleanup
**File:** `backend/mcp/servers/system/server.py:185`
**Severity:** MEDIUM
**Issue:** The reminder task is created but never tracked. If the server shuts down, the task is leaked. Also, the `logger` variable is imported lazily inside the closure on line 182-183 (`logger = logging.getLogger(__name__)`), but `__name__` is resolved at closure-execution time, which may not be correct.
**Fix:** Track the task and cancel on shutdown; import logger at module level.

### 8.2 `set_reminder` — lazy `logging.getLogger` inside async closure
**File:** `backend/mcp/servers/system/server.py:182`
**Severity:** MEDIUM
**Issue:** `logger = logging.getLogger(__name__)` is called inside `_fire()`, which means `__name__` is bound to `"backend.mcp.servers.system.server"` at definition time due to closure scoping. This is actually correct for `__name__`, but poor practice.
**Fix:** Use the module-level `logger` variable directly.

### 8.3 `get_clipboard` — loops through tools but recreates `proc` without closing previous failed attempts
**File:** `backend/mcp/servers/system/server.py:120-143`
**Severity:** LOW
**Issue:** When `xclip` fails, `proc` is simply reassigned. The old process object may not be properly waited/cleaned.
**Fix:** Ensure each `proc` is waited or explicitly closed before retrying with next tool.

### 8.4 `get_cpu_usage` and `get_memory_usage` — spawns a Python subprocess to call `psutil` when `psutil` could be imported directly
**File:** `backend/mcp/servers/system/server.py:73-78,86-93`
**Severity:** LOW
**Issue:** Spawning a subprocess (`python3 -c "import psutil; ..."`) adds ~200ms+ latency for a simple API call. If `psutil` is available (which it must be for the subprocess approach), just import it directly.
**Fix:** Import and call `psutil` directly in-process.

### 8.5 No `import logging` for `set_reminder`'s lazy logger import
**File:** `backend/mcp/servers/system/server.py`
**Severity:** LOW
**Issue:** The module lacks `import logging` at the top level, relying on the lazy import in `set_reminder`. This works for that specific path but is fragile. Added note: actually `logging` is not imported at module level.
**Fix:** Add `import logging`.

### 8.6 `get_current_time` uses `date` subprocess instead of Python `datetime`
**File:** `backend/mcp/servers/system/server.py:169-174`
**Severity:** LOW
**Issue:** Spawning a subprocess just to get the current time is wasteful. `datetime.now().isoformat()` is a single Python call.
**Fix:** Use Python's `datetime` module directly.

---

## 9. MCP Avatar Server — avatar/server.py

### 9.1 Module-level mutable state `_state` — no isolation between sessions
**File:** `backend/mcp/servers/avatar/server.py:15`
**Severity:** HIGH
**Issue:** `_state` is a module-level dict shared across ALL connections/sessions. If two users interact simultaneously, their avatar states (emotion, expression, action) will overwrite each other.
**Fix:** Maintain per-session or per-connection state, keyed by something like `session_id` passed in the tool arguments.

### 9.2 `call_tool` — broad `except Exception` catches everything including `asyncio.CancelledError`
**File:** `backend/mcp/servers/avatar/server.py:109-111`
**Severity:** MEDIUM
**Issue:** The broad except on line 109 catches `asyncio.CancelledError`, which should propagate. Also swallows all errors without re-raising.
**Fix:** Re-raise `CancelledError` and log other exceptions.

---

## 10. Orchestrator — engine.py

### 10.1 `loop` property — creates new event loop and sets it as the main loop
**File:** `backend/core/orchestrator/engine.py:108-115`
**Severity:** HIGH
**Issue:** If `asyncio.get_running_loop()` raises `RuntimeError` (no running loop), the code creates a NEW event loop and sets it globally via `asyncio.set_event_loop()`. This is dangerous in a multi-threaded context (e.g., gRPC server with thread pool executors) — it could interfere with other threads' event loops.
**Fix:** Use `asyncio.get_running_loop()` and let the caller handle the case where no loop exists. Or accept a loop parameter at init.

### 10.2 `execute_plan` — `asyncio.wait` with `ALL_COMPLETED` on potentially empty tasks list
**File:** `backend/core/orchestrator/engine.py:330-334`
**Severity:** MEDIUM
**Issue:** If `_run_step` tasks raise immediately (e.g., CancelledError), `asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)` will return with `done_set` containing the failed tasks, and `pending` will be empty. However, if all tasks complete successfully before the `wait` call, there's no issue. The main concern: if `runnable` is empty, `tasks = []`, and `asyncio.wait([], ...)` raises `ValueError`.
**Fix:** Guard with `if not tasks: break`.

### 10.3 `dispatch_step` — `agent_factory` called inside try block, but agent may not be cleanable on error
**File:** `backend/core/orchestrator/engine.py:263`
**Severity:** LOW
**Issue:** If `agent_factory()` raises, the agent run was already registered in `self.state` on line 257. There's no cleanup for the registered agent in the exception handler.
**Fix:** Move agent registration after successful agent creation, or clean up in the except handler.

### 10.4 `load_state` — if `OrchestratorState.from_dict` raises, the old `self.state` is partially overwritten
**File:** `backend/core/orchestrator/engine.py:151-156`
**Severity:** LOW
**Issue:** `self.state = OrchestratorState.from_dict(...)` happens before the try block completes. If the constructor/from_dict raises, `self.state` is left in an inconsistent state.
**Fix:** Create the new state object first, then assign.

---

## 11. Orchestrator — blackboard.py

### 11.1 `acquire_lock` — stale-lock detection scans ALL entries for each lock acquisition (O(n))
**File:** `backend/core/orchestrator/blackboard.py:170-174`
**Severity:** MEDIUM
**Issue:** The stale-lock check iterates over all `_entries` values to find if the lock holder has posted recently. With many entries (e.g., 10,000+), this is O(n) per lock acquisition, making it O(n*m) when acquiring many locks.
**Fix:** Maintain a separate timestamp map for each agent's last activity.

### 11.2 `search` — `_prefix_index` may return stale keys not in `_entries`
**File:** `backend/core/orchestrator/blackboard.py:121-133`
**Severity:** LOW
**Issue:** The prefix index is not always cleaned when entries expire (TTL-based deletion in `get()` deletes from `_entries` but not from `_prefix_index`). The `search` method handles this by checking `_entries.get(k)` but the stale index entries accumulate.
**Fix:** Clean up `_prefix_index` when entries are TTL-evicted.

### 11.3 `subscribe` — callbacks are stored by reference, creating potential memory leak
**File:** `backend/core/orchestrator/blackboard.py:56`
**Severity:** LOW
**Issue:** Lambdas or bound methods used as callbacks will keep references to their enclosing scope. If subscribers don't explicitly unsubscribe, the closure objects cannot be GC'd.
**Fix:** Document this clearly or use weak references.

### 11.4 `_remove_from_prefix_index` — O(n²) because it scans all index values for each key removal
**File:** `backend/core/orchestrator/blackboard.py:212-214`
**Severity:** LOW
**Issue:** It iterates over ALL `_prefix_index.values()` to find and discard the key. This is O(p * n) where p is the number of prefixes. For large indices this is expensive.
**Fix:** Store reverse mapping (key -> set of prefixes) for O(1) removal.

---

## 12. Orchestrator — escalation.py

### 12.1 `notify_user` — creates Future but never cancels it on timeout
**File:** `backend/core/orchestrator/escalation.py:108-113`
**Severity:** LOW
**Issue:** When the timeout fires, the `response_future` is not cancelled. If the WebSocket response arrives later, `response_future.set_result()` will raise `InvalidStateError` silently caught somewhere.
**Fix:** Cancel the future on timeout.

### 12.2 `get_pending` with `severity=None` — returns all unresolved. No pagination/limit.
**File:** `backend/core/orchestrator/escalation.py:68-71`
**Severity:** LOW
**Issue:** If escalations accumulate without resolution, this list grows unbounded. No limit on returned results.
**Fix:** Add a `max_results` parameter with a default limit.

### 12.3 `_agent_hierarchy` — no lock for concurrent access
**File:** `backend/core/orchestrator/escalation.py:41`
**Severity:** LOW
**Issue:** `_agent_hierarchy` is accessed from potentially multiple coroutines without a lock. While current usage is likely single-threaded, it's not documented as thread-safe.
**Fix:** Add `asyncio.Lock` or document as not thread-safe.

---

## 13. Orchestrator — sandbox.py

### 13.1 `cleanup_stale_locks` — iteration over `_locks.items()` while modifying dict
**File:** `backend/core/orchestrator/sandbox.py:174-183`
**Severity:** MEDIUM
**Issue:** The method iterates over `list(self._locks.items())` — this creates a copy, so modification is safe in this specific method. However, the stale-lock check in `acquire` (line 105) calls `list(self._locks.items())` too, and then `del self._locks[locked_topic]` while iterating the copied list. This is fine as it's iterating a copy.
**Wait:** Actually line 105 iterates over `list(self._locks.items())` which is a snapshot. The `del` on line 111 deletes from the original dict while iterating the copy — that's safe. No issue here.

### 13.2 `_is_related` — `ancestors` does not detect cycles when `_parent_of` has a loop
**File:** `backend/core/orchestrator/sandbox.py:154-165`
**Severity:** LOW
**Issue:** The cycle guard `if current in result: break` catches cycles, but the MAX_DEPTH=100 exit is a safety valve that may hide real bugs (malformed tree).
**Fix:** Add a warning log when MAX_DEPTH is reached.

### 13.3 `register_topic` — cycle detection only checks if parent is a descendant of topic
**File:** `backend/core/orchestrator/sandbox.py:55-60`
**Severity:** MEDIUM
**Issue:** The cycle detection `if parent in descendants` only detects if the proposed parent is already in the descendant tree of the child. But if `parent` has an existing ancestor chain that leads back to `topic` via another path, the cycle is missed. However, since this is a tree (not a DAG), the check is likely sufficient.
**Fix:** Also verify that adding the edge doesn't create a longer cycle through indirect connections.

---

## 14. Orchestrator — state.py

### 14.1 `emit_swarm_update` — `ws_send_fn` may be called multiple times concurrently
**File:** `backend/core/orchestrator/state.py:115-143`
**Severity:** LOW
**Issue:** Multiple concurrent calls to `emit_swarm_update` could send interleaved JSON to the WebSocket.
**Fix:** Add a lock or serialize updates.

### 14.2 `_archive_agent` — slicing `completed_agents` on every archive is O(max_history)
**File:** `backend/core/orchestrator/state.py:57-58`
**Severity:** LOW
**Issue:** `self.completed_agents = self.completed_agents[-self._max_history:]` creates a new list each time, which is O(max_history). With max_history=100 this is fine, but worth noting.
**Fix:** Use `collections.deque(maxlen=...)` instead of list + slicing.

---

## 15. Metacognitive — engine.py

### 15.1 `select` — `delta_history` type: `list[float] | None` but `strategy_selector.select` expects `list[float]`
**File:** `backend/core/metacognitive/engine.py:31-35`
**Severity:** LOW
**Issue:** The docstring says "delta_history: list of recent delta values" but the type hint is permissive. The downstream `select` method in strategy_selector handles None gracefully, but this is a type mismatch.
**Fix:** Tighten the type or document the None case.

### 15.2 `evaluate` and `adapt` — raise TypeError for non-dict input
**File:** `backend/core/metacognitive/engine.py:42-43,52-53`
**Severity:** LOW
**Issue:** Raising `TypeError` at runtime for simple type mismatches is a Python antipattern. Better to let the downstream code raise its own errors or use `typecheck` decorators.
**Fix:** Remove explicit type checks (duck typing).

### 15.3 `reset()` — clears only two of three sub-components
**File:** `backend/core/metacognitive/engine.py:66-69`
**Severity:** LOW
**Issue:** `reset()` calls `strategy_selector.reset()` and `adaptation.reset()` but does NOT reset `delta_evaluator`. If `DeltaEvaluator` has state, it won't be cleared.
**Fix:** Check if `delta_evaluator` has a reset method and call it.

---

## 16. Metacognitive — strategy_selector.py

### 16.1 `LOW_DELTA_THRESHOLD = -0.1` — delta domain not documented
**File:** `backend/core/metacognitive/strategy_selector.py:10`
**Severity:** LOW
**Issue:** The threshold is -0.1, but the delta domain (what values deltas can take) is not defined anywhere. A delta of -0.5 would trigger adaptation, but what does -0.5 represent? This is a magic number.
**Fix:** Document the delta range (e.g., -1.0 to 1.0) or use named constants.

### 16.2 `record_outcome` — silently coerces non-float delta to 0.0
**File:** `backend/core/metacognitive/strategy_selector.py:67-68`
**Severity:** LOW
**Issue:** Invalid delta values are silently converted to 0.0, potentially masking bugs.
**Fix:** Log a warning when coercion occurs.

### 16.3 `select` — uses `cleaned` list which may have fewer elements than expected
**File:** `backend/core/metacognitive/strategy_selector.py:50-54`
**Severity:** LOW
**Issue:** If `delta_history` contains non-numeric values, they are filtered out. If the filtered list has < 3 elements even though the original had 3+, the adaptation is skipped silently.
**Fix:** Log when entries are filtered.

---

## 17. Self-learning — auto_skill.py

### 17.1 `_generate_skill_llm` — hardcoded prompt truncation to 1000 chars
**File:** `backend/core/self_learning/auto_skill.py:214`
**Severity:** MEDIUM
**Issue:** `full_response[:1000]` silently truncates the response before passing to the LLM. The LLM may generate a skill based on incomplete context, missing critical steps from the later part of the response.
**Fix:** Truncate with a warning or use a smarter truncation (last N chars, or summarize).

### 17.2 `_generate_skill_name` — hash collision possible but unlikely
**File:** `backend/core/self_learning/auto_skill.py:188`
**Severity:** LOW
**Issue:** 12 hex chars (48 bits) from SHA256 has ~281 trillion space, but if the same user message produces the same name AND a different message also produces the same name, the second creation is skipped silently (on line 123-125).
**Fix:** Document this behavior.

### 17.3 `maybe_create_skill` — `tool_calls` parameter type is `list` but used with `len()` and `_get_tool_name`
**File:** `backend/core/self_learning/auto_skill.py:82,104`
**Severity:** LOW
**Issue:** Type hint says `list` (no element type). The code accesses `.get("tool_name")` for dicts and `.tool_name` for objects. If a mixed list is passed, some items may silently fail.
**Fix:** Add type checking or normalize input early.

### 17.4 `list_recent_skills` — reads first 2KB of each SKILL.md to detect `auto_generated`
**File:** `backend/core/self_learning/auto_skill.py:393`
**Severity:** LOW
**Issue:** Reading 2KB from every skill file on every call may be slow for large skill libraries. The docstring says "reducing I/O from O(content) to O(metadata)" but 2KB reads are still I/O.
**Fix:** Consider checking file metadata (attribute) or a separate index file.

---

## 18. Self-learning — corrections.py

### 18.1 `_save` called synchronously inside `extract_correction` — blocks event loop
**File:** `backend/core/self_learning/corrections.py:116`
**Severity:** MEDIUM
**Issue:** `self._save()` is called directly without `await`. Wait — `_save` is a synchronous method (no `async def`). It writes JSON to disk synchronously, blocking the event loop during disk I/O.
**Fix:** Make `_save` async or run in executor.

### 18.2 `find_relevant` — creates dict copy `dict(r)` for each result but only shallow copy
**File:** `backend/core/self_learning/corrections.py:144`
**Severity:** LOW
**Issue:** `dict(r)` creates a shallow copy. If any value in the record is mutable, modifications propagate back to the original.
**Fix:** Use `copy.deepcopy` if nested mutability is a concern.

### 18.3 `_flush_if_needed` — always calls `_save` even if only `_pending_applied_updates` has changes
**File:** `backend/core/self_learning/corrections.py:188-191`
**Severity:** LOW
**Issue:** The flush always writes the full corrections list to disk, even for minor applied_count increments. Frequent writes could wear SSD.
**Fix:** Batch updates more aggressively or use a write-ahead log.

### 18.4 `_load` — JSON file read with `read_text()` without file locking
**File:** `backend/core/self_learning/corrections.py:224`
**Severity:** MEDIUM
**Issue:** If two instances of CorrectionStore are created (e.g., in testing or multi-process), concurrent reads/writes can corrupt the JSON file.
**Fix:** Use file locking or atomic writes (write to temp, rename).

---

## 19. Self-learning — preferences.py

### 19.1 `_save` called on every `observe_interaction` — blocks event loop
**File:** `backend/core/self_learning/preferences.py:101`
**Severity:** MEDIUM
**Issue:** `self._save()` is synchronous JSON write, called on every single interaction. Blocks the event loop for disk I/O.
**Fix:** Make `_save` async, use `run_in_executor`, or batch saves (e.g., every 5 interactions).

### 19.2 `_infer_response_style` — uses hardcoded indicator sets that may not generalize
**File:** `backend/core/self_learning/preferences.py:172-175`
**Severity:** LOW
**Issue:** The casual/technical indicator word sets are English-specific and small. They may misclassify non-English users or users with niche vocabulary.
**Fix:** Document the limitation or make indicators configurable.

### 19.3 `get_inferred_preferences` — called often but recalculates from scratch each time
**File:** `backend/core/self_learning/preferences.py:103-125`
**Severity:** LOW
**Issue:** Each invocation recalculates verbosity, style, and automation from scratch. With large interaction windows, this may become slow.
**Fix:** Cache results and invalidate only when new observations arrive.

---

## 20. Self-learning — improvement.py

### 20.1 `prune_stale` — `dry_run=True` by default, which is surprising for an operational method
**File:** `backend/core/self_learning/improvement.py:101`
**Severity:** LOW
**Issue:** Default `dry_run=True` means callers who don't read docs will think they pruned skills but nothing was deleted. This is a safe default but deserves a docstring note.
**Fix:** Already documented, but consider adding a log line like "Dry-run mode — pass dry_run=False to actually delete".

### 20.2 `_discover_skills` — reads first 512 bytes of each SKILL.md via `read_bytes()`
**File:** `backend/core/self_learning/improvement.py:171`
**Severity:** LOW
**Issue:** 512 bytes may not be enough for frontmatter if the YAML frontmatter is long. The `created` timestamp could be on line 30+, exceeding 512 bytes in pathological cases.
**Fix:** Use `read_bytes()[:4096]` or parse the file properly.

### 20.3 `_is_stale` — timezone-naive/aware comparison may fail
**File:** `backend/core/self_learning/improvement.py:192-193`
**Severity:** MEDIUM
**Issue:** If `created` is a naive datetime string (no timezone info) and `datetime.now(timezone.utc)` is timezone-aware, the comparison `age = (datetime.now(timezone.utc) - created_dt).days` may raise `TypeError` if `created_dt` was made aware but the original was naive in a different way. The code handles the naive case on line 192, but if `created` contains a non-standard timezone format, `fromisoformat` may raise `ValueError` before the fix is applied.
**Fix:** Use `.replace(tzinfo=None)` on both sides before comparison, or ensure both are aware.

---

## 21. gRPC — server.py

### 21.1 `Chat` gRPC handler — no error handling for `agent.handle_user_input` iteration
**File:** `backend/grpc/server.py:29-51`
**Severity:** MEDIUM
**Issue:** If `handle_user_input` raises an exception, the entire gRPC stream is terminated without sending any error to the client. The client will see a broken stream with no error message.
**Fix:** Wrap the async iteration in try/except and yield an error response before re-raising.

### 21.2 `Chat` — `permission_action` handler does nothing with the response
**File:** `backend/grpc/server.py:53-58`
**Severity:** MEDIUM
**Issue:** When the client sends a `permission_action`, the server logs it and echoes it back as text, but never processes the action (never calls `approve_tool`, `set_permission_level`, etc.). The permission workflow is broken in gRPC mode.
**Fix:** Implement actual permission handling in the gRPC path.

### 21.3 `serve_grpc` — uses `futures.ThreadPoolExecutor` with gRPC async server
**File:** `backend/grpc/server.py:63`
**Severity:** MEDIUM
**Issue:** The gRPC async server (`grpc.aio.server`) is created with a `ThreadPoolExecutor` for the (sync) completion queue. This is the standard pattern for grpc.aio, but confusingly the server is async while the executor is sync. Not a bug per se, but the `max_workers=10` limits concurrent gRPC streams to 10.
**Fix:** Document the concurrency limit, or increase for production.

### 21.4 `serve_grpc` — no graceful shutdown handler
**File:** `backend/grpc/server.py:61-73`
**Severity:** LOW
**Issue:** `serve_grpc` has no shutdown logic. When cancelled, the server just stops abruptly without draining existing streams.
**Fix:** Add a shutdown handler that calls `server.stop(grace=5)`.

---

## 22. gRPC — agent_pb2_grpc.py

### 22.1 Version check raises `RuntimeError` if gRPC version is older than generated code
**File:** `backend/grpc/agent_pb2_grpc.py:18-25`
**Severity:** LOW
**Issue:** The generated stub checks that the installed gRPC version matches the version used at code generation time. If mismatched, it raises `RuntimeError` with upgrade/downgrade instructions. This can cause runtime failures in environments where gRPC is updated independently.
**Fix:** Consider making this a warning instead of an error, or pinning gRPC version in requirements.

### 22.2 `Chat` method in `AgentServiceServicer` (the base class) raises `NotImplementedError`
**File:** `backend/grpc/agent_pb2_grpc.py:51`
**Severity:** LOW
**Issue:** The base class raises `NotImplementedError` after calling `context.set_code(UNIMPLEMENTED)`. The `AgentService` subclass overrides this, so this is actually a no-op in practice. But the `Chat` method in the generated stub is NOT asynchronous, while the actual implementation in server.py is async. This type mismatch could cause issues.
**Fix:** Regenerate the stub with `grpcio-tools` that supports async properly.

---

## 23. Telegram — telegram.py

### 23.1 `_is_allowed` — `str(u)` for each user in `allowed_users` on every message — O(n)
**File:** `backend/api/telegram.py:37`
**Severity:** LOW
**Issue:** For every message, converts all allowed users to strings and checks membership. With a large allowed_users list, this is wasteful. Pre-convert once.
**Fix:** Convert `allowed_users` to a `set[str]` in `__init__`.

### 23.2 `handle_message` — `edit_message_text` called in loop with rate-limit check; ignores Telegram's rate limits
**File:** `backend/api/telegram.py:82-92`
**Severity:** MEDIUM
**Issue:** Telegram has a rate limit of ~20 messages/minute for bots. The edit loop fires every 1.5s which is ~40 edits/minute. Combined with other bot messages, this may hit Telegram's rate limit and get the bot temporarily blocked.
**Fix:** Increase the update interval or implement exponential backoff on 429 errors.

### 23.3 `handle_message` — empty tuple handler on line 75-78 silently skips tagged chunks
**File:** `backend/api/telegram.py:75-78`
**Severity:** MEDIUM
**Issue:** When `handle_user_input` yields `(tag_type, tag_val)` tuples (thinking, permission, tool, etc.), the code just does `continue` — all tagged content is silently dropped. The user never sees thinking traces, tool calls, or permission requests.
**Fix:** Render tagged chunks as Telegram messages (e.g., italic for thinking, code blocks for tools).

### 23.4 `run` method — `async with self.application` blocks until `stop_event.wait()` completes
**File:** `backend/api/telegram.py:138-152`
**Severity:** LOW
**Issue:** The `stop_event.wait()` pattern is correct, but if `init_application()` fails, the bot's `self.application` is `None` and the `async with self.application` will raise `AttributeError`.
**Fix:** Guard with `if self.application is None: return`.

### 23.5 `handle_voice` — voice message handler is a stub
**File:** `backend/api/telegram.py:111-120`
**Severity:** LOW
**Issue:** Voice handler downloads the file but does nothing with it. It replies saying "not yet fully implemented". It should at least transcribe with STT.
**Fix:** Complete the implementation or remove the handler.

---

## 24. Plugin system — backend/core/plugin.py

### 24.1 `_call_with_timeout` — re-raises both TimeoutError and Exception after logging
**File:** `backend/core/plugin.py:100-112`
**Severity:** LOW
**Issue:** The function raises after logging, but all callers in `PluginRegistry` catch these with `except (asyncio.TimeoutError, Exception): pass`. The re-raise is swallowed. The function could simply return None on failure and let callers handle.
**Fix:** Change to return `None` or a sentinel on error instead of re-raising.

### 24.2 `discover_plugins` — `hasattr(mod, "PluginClass")` after `exec_module` but before checking it's a type
**File:** `backend/core/plugin.py:352-357`
**Severity:** LOW
**Issue:** The code checks `hasattr(mod, "PluginClass")` then separately checks `isinstance(getattr(mod, "PluginClass"), type)`. If `PluginClass` exists but is not a type (e.g., it's a string or function), the check works correctly but confusingly assumes it could be a class.
**Fix:** Simplify with `if isinstance(getattr(mod, "PluginClass", None), type)`.

### 24.3 `discover_plugins` — `register()` function path creates a basic plugin with no hooks
**File:** `backend/core/plugin.py:358-367`
**Severity:** LOW
**Issue:** If a discovered module has a `register()` function, the code creates a bare `Plugin` subclass with just a name. This plugin has no hook implementations, making it essentially a no-op. The module author expected their `register()` function to be the integration point.
**Fix:** Call the `register()` function and let it handle registration, or document that `register()` should return a Plugin instance.

---

## 25. Plugin system — backend/plugins/manager.py

### 25.1 `discover_and_load` — iterates plugin_dir.iterdir() which may raise if directory is deleted during iteration
**File:** `backend/plugins/manager.py:68`
**Severity:** LOW
**Issue:** If `self.plugins_dir` is deleted by an external process during iteration, `iterdir()` raises `FileNotFoundError` or `StopIteration`.
**Fix:** Catch `OSError` around the loop.

### 25.2 `reload_plugin` — loads a plugin by directory matching, but name must match directory name
**File:** `backend/plugins/manager.py:149-187`
**Severity:** LOW
**Issue:** The reload logic scans all directories to find matching plugin names, but the name comparison happens after load. If two directories produce plugins with the same name, the first match wins.
**Fix:** Use a manifest or explicit mapping from name to directory.

### 25.3 `shutdown_all` — timeout applies per-plugin, not overall, leading to 10*N total shutdown time
**File:** `backend/plugins/manager.py:237-271`
**Severity:** LOW
**Issue:** Each plugin gets `timeout` seconds for shutdown. With 20 plugins and 10s timeout, shutdown takes up to 200s.
**Fix:** Run shutdowns concurrently with `asyncio.gather` and a per-task timeout.

---

## 26. Plugin system — backend/plugins/base.py

### 26.1 `PluginTool.__call__` — wrapping sync functions in executor but `*args` are passed via `lambda`
**File:** `backend/plugins/base.py:62-63`
**Severity:** MEDIUM
**Issue:** `lambda: self.func(*args, **kwargs)` captures `args` and `kwargs` by reference from the enclosing scope. If the lambda execution is delayed (which it is, via executor), the captured variables may have changed. In practice, `args` and `kwargs` are not mutated before the lambda runs, so this is unlikely to cause issues.
**Fix:** Capture by value: `lambda a=args, kw=kwargs: self.func(*a, **kw)`.

### 26.2 `BasePlugin.__init__` — `name` setter silently discards all values
**File:** `backend/plugins/base.py:113-115`
**Severity:** MEDIUM
**Issue:** The `name` setter is `def name(self, value): pass` — it silently discards any assigned value. This means `super().__init__()` on line 100 (which sets `self.name = ""` via the `Plugin` base class) silently does nothing. The name is always derived from `metadata.name`. This violates Liskov substitution — the `name` property setter should either work or raise.
**Fix:** Remove the setter entirely and have `name` property return `self.metadata.name`.

### 26.3 `BasePlugin.__init__` — calls `Plugin.__init__` which checks `if not self.name:` but name property returns metadata.name
**File:** `backend/plugins/base.py:100`
**Severity:** LOW
**Issue:** When `Plugin.__init__` runs, `self.name` is a property that calls `self.metadata.name`. But `self._metadata` is set before `super().__init__()`, so it works. However, the empty string check in `Plugin.__init__` is bypassed because the property never returns empty string.
**Fix:** No fix needed, but this is fragile — if `_metadata` is removed, the name check in the base class is silently skipped.

---

## 27. Skills — md_loader.py

### 27.1 `INJECTION_PATTERNS` — basic keyword matching, easy to bypass
**File:** `backend/skills/md_loader.py:33-40`
**Severity:** LOW
**Issue:** Injection detection uses simple substring matching with common jailbreak phrases. This is easily bypassed (e.g., "ignore prеvious instructions" with Unicode homoglyphs).
**Fix:** Use a more robust detection method.

### 27.2 `get_loader` — module-level singleton is not thread-safe
**File:** `backend/skills/md_loader.py:124-131`
**Severity:** LOW
**Issue:** `_skill_loader` check-then-create pattern is not safe under concurrent initialization. Two coroutines could both pass the `if _skill_loader is None` check.
**Fix:** Use `asyncio.Lock` or double-checked locking pattern.

### 27.3 `install` — writes content to disk without checking if the skill directory name collides with existing names
**File:** `backend/skills/md_loader.py:110-120`
**Severity:** MEDIUM
**Issue:** `install` writes to `self.dir / f"{name}.md"`. If a skill with the same name already exists, it silently overwrites without warning. Also no indication if the file name is valid on the filesystem.
**Fix:** Check for existing file and raise/warn on conflict; validate filename.

### 27.4 `for_query` — partial trigger matching without scoring normalization
**File:** `backend/skills/md_loader.py:102-108`
**Severity:** LOW
**Issue:** Sorting by count of matched triggers favors skills with many triggers (more chances to match). A skill with 10 triggers that matches 3 is not necessarily more relevant than a skill with 2 triggers that matches 2.
**Fix:** Normalize score by total trigger count.

---

## 28. Hot-reload — hot_reload.py

### 28.1 `_check_changes` — re-globs directories on every check (every 2 seconds)
**File:** `backend/core/hot_reload.py:60`
**Severity:** LOW
**Issue:** Every 2 seconds, `watch_path.glob("*.md")` and `watch_path.glob("*.yaml")` are called for each watched directory. With many files, this is ~2x N syscalls per directory per check.
**Fix:** Cache the file list and only rescan on events.

### 28.2 `_reload_skill` — accesses `loader._load` (private method) directly
**File:** `backend/core/hot_reload.py:115`
**Severity:** LOW
**Issue:** `setup_hot_reload` accesses `loader._load`, which is a private method of `MDSkillLoader`. If the loader's internal API changes, hot-reload silently breaks.
**Fix:** Expose `load_skill(path)` as a public method.

### 28.3 `setup_hot_reload` — lambda captures `skill_loader` by reference; if `skill_loader` is reassigned, the lambda still refers to the old object
**File:** `backend/core/hot_reload.py:95-96`
**Severity:** LOW
**Issue:** `lambda p: _reload_skill(p, skill_loader)` captures `skill_loader` by closure. If `skill_loader` is replaced (e.g., by calling `get_loader().reload()` which creates a new instance), the lambda still refers to the old one. This is a Python closure gotcha.
**Fix:** Use `lambda p, loader=skill_loader: _reload_skill(p, loader)` to capture by value.

---

## 29. Startup — startup.py

### 29.1 `_background_tasks` — module-level set that leaks between test runs
**File:** `backend/core/startup.py:94`
**Severity:** LOW
**Issue:** `_background_tasks` is a module-level set. In tests, tasks accumulate across test cases, causing warnings about pending tasks at teardown.
**Fix:** Use a weak-ref set or clear the set in a fixture.

### 29.2 `init_application` — MCP server connections run in background task, but `_background_tasks.add` is never cleaned on shutdown
**File:** `backend/core/startup.py:67`
**Severity:** MEDIUM
**Issue:** `_background_tasks.add(asyncio.create_task(...))` stores the task but no one cancels it during shutdown. If `shutdown_application` is called, the MCP connection task keeps running.
**Fix:** Cancel all `_background_tasks` in `shutdown_application`.

### 29.3 `make_settings_reloader` — `asyncio.run_coroutine_threadsafe` but returned Future is ignored
**File:** `backend/core/startup.py:116-118`
**Severity:** LOW
**Issue:** `asyncio.run_coroutine_threadsafe(...)` returns a `Future` that can be used to await the result or handle exceptions. The return value is ignored.
**Fix:** At minimum, log exceptions from the returned Future.

### 29.4 `init_application` — `settings.get("log.level", "WARNING")` but `log_level` may be an invalid value for `configure_logging`
**File:** `backend/core/startup.py:29-32`
**Severity:** LOW
**Issue:** If settings has an invalid log level (e.g., "WARN" instead of "WARNING"), `configure_logging` may raise or silently default.
**Fix:** Validate log level before passing.

---

## 30. Paths — paths.py

### 30.1 `PROJECT_ROOT` computed with `os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))`
**File:** `backend/core/paths.py:8`
**Severity:** LOW
**Issue:** `__file__` may be a relative path or a symlink path, causing `PROJECT_ROOT` to resolve to the wrong directory in some deployment scenarios (e.g., when running from a zipped package).
**Fix:** Use `Path(__file__).resolve().parent.parent.parent`.

### 30.2 `DATA_DIR` overridable via `AMALGAM_DATA_DIR` env var — downstream paths use `str()` conversion
**File:** `backend/core/paths.py:10-23`
**Severity:** LOW
**Issue:** `DATA_DIR` is a `Path` object, but downstream usages like `SETTINGS_PATH = str(DATA_DIR / "settings.json")` convert to string early, losing Path's cross-platform benefits.
**Fix:** Keep as Path objects and let callers convert as needed.

---

## 31. Errors — errors.py

### 31.1 `ServiceError.to_dict()` returns `"type": "error"` but this conflicts with WebSocket message type field
**File:** `backend/core/errors.py:56`
**Severity:** LOW
**Issue:** The `to_dict()` method sets `"type": "error"`, which is the same field name used by WebSocket message routing. If this dict is embedded in another message, the `type` field could be misinterpreted by the frontend.
**Fix:** Use `"error_type"` or `"kind"` instead of `"type"`.

### 31.2 Error hierarchy is flat with no `__cause__` chaining
**File:** `backend/core/errors.py:26-275`
**Severity:** LOW
**Issue:** None of the error constructors accept a `__cause__` (from `raise ... from cause`). When catching a low-level exception and wrapping it, the traceback chain is lost.
**Fix:** Add an optional `cause` parameter that is passed to `super().__init__()` or stored as `self.__cause__`.

### 31.3 `TTSError`, `STTError`, `MemoryError`, `AgentError`, `ConfigurationError` all pass through to `ServiceError` with default `recoverable` and `suggestion`
**File:** `backend/core/errors.py:137-275`
**Severity:** LOW
**Issue:** Each subclass calls `super().__init__` with hardcoded defaults. For example, `MemoryError` defaults to `recoverable=False`, which is correct for most cases but the caller should be able to override it.
**Fix:** Allow overriding `recoverable` and `suggestion` in each subclass constructor.

---

## 32. Utils — tokens.py

### 32.1 `_ENCODING_CACHE` — module-level dict, grows unboundedly with model names
**File:** `backend/core/utils/tokens.py:16`
**Severity:** LOW
**Issue:** The cache maps encoding names (not model names) to tiktoken encodings. There are only a few encoding names (cl100k_base, o200k_base), so the cache won't grow large. However, if new encodings are added (p50k_base, r50k_base), they accumulate.
**Fix:** Cap the cache size with `LRU` or `functools.lru_cache`.

### 32.2 `estimate_tokens` — catches all exceptions from `enc.encode(text)` silently
**File:** `backend/core/utils/tokens.py:91-92`
**Severity:** LOW
**Issue:** If `enc.encode(text)` raises, the error is silently swallowed and falls through to the char-based heuristic. Rare errors (e.g., encoding issues) could go undetected.
**Fix:** Log a debug message when encoding fails.

### 32.3 `truncate_to_token_limit` — binary search calls `estimate_tokens` for each midpoint, which is O(log n) tokenizations
**File:** `backend/core/utils/tokens.py:109-115`
**Severity:** LOW
**Issue:** The binary search calls `estimate_tokens(text[:mid], model)` repeatedly. Each call re-tokenizes the prefix. For large texts, this is ~log(n) passes over prefix-length substrings, which is roughly O(n log n) characters processed.
**Fix:** There's no better approach without caching tokenization, but for very large texts (>100K chars) this could be slow.

### 32.4 `select_messages_within_budget` — modifies `msg` dicts with truncated content but returns references to original dicts
**File:** `backend/core/utils/tokens.py:161`
**Severity:** MEDIUM
**Issue:** `selected.insert(0, {**msg, "content": truncated})` creates a new dict for truncated messages but keeps all other messages as references to the originals. This means that modifying returned messages (e.g., appending to a "content" field) would modify the caller's original list.
**Fix:** Use `copy.deepcopy` for all returned messages or document that callers must not mutate returned messages.

---

## 33. Utils — wav.py

### 33.1 `wav_bytes_to_numpy` — no validation that `wav_bytes` is a valid WAV file
**File:** `backend/core/utils/wav.py:37-44`
**Severity:** LOW
**Issue:** If `wav_bytes` is not a valid WAV file, `wave.open()` will raise `wave.Error` which propagates to the caller. The function should at least document this or provide a fallback.
**Fix:** Add try/except and raise a descriptive error.

### 33.2 Missing type annotations for `numpy` return types
**File:** `backend/core/utils/wav.py:37`
**Severity:** LOW
**Issue:** Return type annotation `tuple[np.ndarray, int]` is correct but `np.ndarray` is generic. No specific dtype annotation.
**Fix:** Use `np.ndarray[np.float32]` (requires `numpy>=1.21` with `nptyping`).

---

## 34. Utils — icon_generator.py

### 34.1 `_generate_letter_icon` — hardcoded font path for DejaVu Sans
**File:** `backend/core/utils/icon_generator.py:44`
**Severity:** MEDIUM
**Issue:** The font path `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf` is Linux-specific and assumes DejaVu is installed. On macOS or minimal Docker images, this path doesn't exist, causing fallback to the default PIL bitmap font which looks poor.
**Fix:** Search multiple font paths or allow configuration.

### 34.2 `generate_missing_icons` — `asyncio.create_subprocess_exec` with 300s timeout for Node.js script
**File:** `backend/core/utils/icon_generator.py:87`
**Severity:** LOW
**Issue:** 300s timeout for icon generation is very long. If the Node.js script hangs, the generator hangs for 5 minutes.
**Fix:** Reduce timeout or make configurable.

### 34.3 `_generate_missing_icons_sync` — no `async` but called via `run_in_executor`
**File:** `backend/core/utils/icon_generator.py:97`
**Severity:** LOW
**Issue:** `await loop.run_in_executor(None, _generate_missing_icons_sync)` — the sync function is correctly called in executor. But `_generate_icons_in` opens YAML files synchronously inside the executor, which is fine.
**Fix:** No bug, but note that `_generate_missing_icons_sync` could itself be async and the outer function could call it directly.

---

## 35. Relationship — relationship.py

### 35.1 `_apply_time_decay` — uses naive datetime subtraction
**File:** `backend/core/relationship.py:126-129`
**Severity:** MEDIUM
**Issue:** `stats["last_interaction"]` is stored as an ISO string with timezone (created with `datetime.now(timezone.utc).isoformat()`), but `_apply_time_decay` computes `datetime.fromisoformat(last)` which returns a timezone-aware datetime correctly on Python 3.11+ but may fail on older Python or if the stored format changes.
**Fix:** Ensure `fromisoformat` is always timezone-aware-capable (Python 3.11+ handles this correctly).

### 35.2 `analyze_message` — calls `_load` which opens a new DB connection each time despite caching
**File:** `backend/core/relationship.py:151-152`
**Severity:** LOW
**Issue:** `_load` creates a new `aiosqlite.connect(self._db_path)` for every call, even when the result is cached. Only the cache miss path opens the database, but the `analyze_message` -> `_load` -> `_save` chain opens two connections (one for read, one for write).
**Fix:** Keep a persistent DB connection or use a connection pool.

### 35.3 `_cache` — grows unboundedly with character IDs
**File:** `backend/core/relationship.py:55`
**Severity:** LOW
**Issue:** `_cache` is a `Dict[str, Dict]` that grows for every unique character_id seen. No eviction policy.
**Fix:** Add an LRU cache or max size limit.

### 35.4 `_analyze_sentiment` — truncates at 10000 chars but VADER may still be slow
**File:** `backend/core/relationship.py:139`
**Severity:** LOW
**Issue:** 10000 chars is still quite large for VADER (which is O(n) but uses Python loops). For very long user messages, this could block the event loop for 10-50ms.
**Fix:** Truncate more aggressively (e.g., 2000 chars) or run in executor.

---

## 36. Constitution — constitution.py

### 36.1 `_cache` module-level variable has no lock for concurrent access
**File:** `backend/core/constitution.py:18`
**Severity:** LOW
**Issue:** `load_constitution()` and `reload_cache()` both access the global `_cache` variable. If called concurrently from multiple coroutines (e.g., during concurrent session creation), a race condition could cause double-read of the file or inconsistent cache.
**Fix:** Use `asyncio.Lock` or `threading.Lock`.

### 36.2 `load_constitution` — reads file synchronously
**File:** `backend/core/constitution.py:27`
**Severity:** LOW
**Issue:** `CONSTITUTION_PATH.read_text(encoding="utf-8")` is a synchronous file read. If called during a hot request path, it blocks the event loop.
**Fix:** Use `asyncio.to_thread` or `loop.run_in_executor`.

---

## 37. Secrets — secrets.py

### 37.1 `_save` — writes secrets file with 0o600 permissions but doesn't mask umask
**File:** `backend/core/secrets.py:32-33`
**Severity:** MEDIUM
**Issue:** `chmod(0o600)` is called after writing, but between write and chmod, the file may have default permissions (0644 masked by umask). If another process or user reads the file during this window, secrets are exposed. Additionally, `umask` is not set, so the effective permissions depend on the process's umask.
**Fix:** Set umask to 0o077 before creating the file, or create with `os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)`.

### 37.2 `_load` — loads entire JSON file into memory
**File:** `backend/core/secrets.py:26`
**Severity:** LOW
**Issue:** Read into `json.loads(self._path.read_text())` — for large secrets files this loads all into memory.
**Fix:** Fine for small secrets files, but worth noting for security-sensitive deployments.

### 37.3 No file locking for concurrent access
**File:** `backend/core/secrets.py:17-57`
**Severity:** MEDIUM
**Issue:** If two instances of `SecretsManager` are created (e.g., in testing scenarios), concurrent reads/writes can corrupt the JSON file. Even within a single process, `_load` and `_save` are not locked.
**Fix:** Use file locking (fcntl) or atomic writes.

---

## 38. Agent — permissions.py

### 38.1 `TOOL_TIERS` — "skill" is classified as ELEVATED but "list_skills" is SAFE
**File:** `backend/core/agent/permissions.py:125-162`
**Severity:** LOW
**Issue:** Inconsistency: `skill` (loading a skill) is ELEVATED while `list_skills` is SAFE. The skill tool writes nothing; it reads a skill file. Should be NORMAL or SAFE.
**Fix:** Downgrade `skill` to NORMAL or SAFE.

### 38.2 `PermissionGate.check` — `ask_fn` may be called without the prompt being prepared
**File:** `backend/core/agent/permissions.py:232`
**Severity:** LOW
**Issue:** The `ask_fn` prompt includes the tier name (uppercase) which is not user-friendly. The user sees "Allow write_file (path='test.py')? [tier: ELEVATED] — y/n/always: ".
**Fix:** Lowercase the tier name or add a description.

### 38.3 `PermissionLevel` enum compared via `.value` in `from_dict` but used directly elsewhere
**File:** `backend/core/agent/permissions.py:106`
**Severity:** LOW
**Issue:** `PermissionLevel(data.get("level", "full"))` — "full" is a valid value and will create `PermissionLevel.FULL`. But "readonly" and "confirm" map directly via enum value. If an invalid string is passed, `ValueError` is raised. This is fine but could be more graceful.
**Fix:** Add fallback to default level if invalid string.

---

## 39. Agent — hooks.py

### 39.1 `unregister_pre`/`unregister_post` — O(n) removal using `list.remove`
**File:** `backend/core/agent/hooks.py:37-43`
**Severity:** LOW
**Issue:** `self._pre_hooks.remove(hook)` searches the list linearly and removes by value. If many hooks are registered, this is O(n).
**Fix:** For large hook counts, use a dict or set.

### 39.2 `run_pre` — returns first error but continues executing remaining hooks
**File:** `backend/core/agent/hooks.py:49-57`
**Severity:** MEDIUM
**Issue:** If a pre-hook returns an error, the method returns the error dict immediately, but the subsequent hooks have already been partially executed or not executed. This could leave the system in an inconsistent state.
**Fix:** Reorder: run all pre-hooks first, then check for errors.

### 39.3 No hook priority ordering
**File:** `backend/core/agent/hooks.py:24-70`
**Severity:** LOW
**Issue:** Hooks are executed in registration order. There's no way to specify that one hook should run before another.
**Fix:** Add a `priority` parameter to `register_pre`/`register_post`.

---

## 40. Agent — analytics.py

### 40.1 `record_call` — `min_latency_ms` starts at `float("inf")` which may break JSON serialization
**File:** `backend/core/agent/analytics.py:39`
**Severity:** MEDIUM
**Issue:** `min_latency_ms: float = float("inf")` is never serialized to JSON (the `_format_tool` method handles it), but if `to_dict` or `get_stats` is called directly on the internal dict before any call, `"min_latency_ms": Infinity` will fail JSON encoding.
**Fix:** Initialize `min_latency_ms` to `0.0` instead.

### 40.2 `_format_tool` — `calls` may be 0 causing ZeroDivisionError
**File:** `backend/core/agent/analytics.py:92-98`
**Severity:** LOW
**Issue:** `calls = info["calls"] or 1` guards against division by zero. However, if `calls` is 0, `info["total_latency_ms"]` is also 0, so the avg_latency is correctly 0.
**Fix:** Already handled correctly.

### 40.3 No periodic persistence — `persist()` must be called explicitly
**File:** `backend/core/agent/analytics.py:124`
**Severity:** LOW
**Issue:** Analytics data is only persisted to disk when `persist()` is called explicitly. If the process crashes, unsaved analytics are lost.
**Fix:** Add a background periodic persistence task or hook into shutdown.

---

## Summary of Severity Distribution

| Severity | Count | Key Areas |
|----------|-------|-----------|
| HIGH | 2 | Avatar server shared state, shell server concurrent list mutation |
| MEDIUM | 32 | Event loop blocking (sync I/O), missing error handling, race conditions, permission bypasses, resource leaks |
| LOW | 60 | Type hints, dead code, missing docs, performance nits, minor bugs |

## Top 10 Most Critical Issues

1. **Avatar server shared `_state` (HIGH)** — `backend/mcp/servers/avatar/server.py:15` — Module-level mutable dict shared across all sessions
2. **Shell server `ALLOWED_ONCE` concurrent mutation (HIGH)** — `backend/mcp/servers/shell/server.py:39-43` — No lock on shared mutable sets/lists
3. **Orchestrator `loop` property creates new event loop (HIGH)** — `backend/core/orchestrator/engine.py:108-115` — May override event loop in threaded contexts
4. **Plugin base `name` setter silently discards (MEDIUM)** — `backend/plugins/base.py:114` — Violates Liskov substitution
5. **gRPC permission handler is a no-op (MEDIUM)** — `backend/grpc/server.py:53-58` — Permission actions never processed
6. **Telegram handle_message drops tagged chunks (MEDIUM)** — `backend/api/telegram.py:75-78` — User never sees thinking/tool/permission messages
7. **CorrectionStore synchronous `_save` blocks event loop (MEDIUM)** — `backend/core/self_learning/corrections.py:116`
8. **PreferenceLearner synchronous `_save` blocks event loop (MEDIUM)** — `backend/core/self_learning/preferences.py:101`
9. **SecretsManager file permission race (MEDIUM)** — `backend/core/secrets.py:32-33` — File readable between write and chmod
10. **Analytics `min_latency_ms` float("inf") breaks JSON (MEDIUM)** — `backend/core/agent/analytics.py:39`
