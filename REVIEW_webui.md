# WebUI Frontend Code Review

Generated: 2026-06-22

## Executive Summary

Reviewed **47 files** (~6,500 lines of JS + CSS + HTML). Found **3 high-severity** (XSS, memory leaks in active paths), **7 medium-severity** (unhandled rejections, leaky observers, dangling listeners), and **15+ low-severity** issues (console.log in prod, fragile patterns, missing guards, minor cleanup gaps). The codebase is well-structured with ES modules, proper `escHtml()` usage in most places, and generally good cleanup in `destroy()` methods. Below is a file-by-file breakdown.

---

## JS Modules (webui/js/modules/)

---

### api-client.js — 35 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 29 | LOW | `JSON.parse(text)` throws on invalid JSON. While checked `r.ok`, a non-JSON 200 response will crash. | Wrap in try/catch or use `response.json()` instead of manual parse. |

---

### companion.js — 100 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 90 | INFO | `removeEventListener` uses `_resetIdleTracker` as handler — correctly matches the addEventListener on line 85. No issue. | — |

---

### config.js — 45 lines

No issues found.

---

### health.js — 33 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 32 | LOW | Silent catch on `refreshHealth()`. Intentional (health bar stays unknown). | Consider logging once on first failure. |

---

### history.js — 180 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 65–68 | **MEDIUM** | **Race condition:** `location.hash` is changed asynchronously, then a new session is fetched. If multiple rapid deletes occur, the hash reflects stale data. | Guard with a debounce or compare session IDs before overwriting. |
| 149–153 | **MEDIUM** | **Unhandled promise rejection:** `res.json()` on search response. If the endpoint returns non-JSON (e.g. 502 HTML), the promise rejects uncaught. | Add `.catch()` or wrap in try/catch. |
| 170–178 | LOW | `item.innerHTML` with `escHtml()` — safe. But each result item creates a new `click` listener. | For large result sets, consider event delegation. |

**Also:** `_historySearchAbort` is an AbortController — good pattern for cancelling in-flight searches.

---

### markdown.js — 211 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 159–167 | **MEDIUM** | **Inline `onclick` in generated HTML** — uses string-based event handler. The code is hardcoded and escaped, but `onclick` strings are an XSS vector if any interpolated value becomes user-controlled. Currently safe because `codeContent` is pre-escaped. | Refactor to use `addEventListener` instead of inline `onclick`. |
| 29 | LOW | Regex-based markdown parsing is fragile (nested backticks, escaped backticks). | Consider using a markdown library. |

---

### mcp.js — 71 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 47–51 | LOW | `fetch().catch(() => {})` swallows errors silently. | Log a warning at minimum. |
| 23, 67 | OK | `innerHTML` with `escHtml()` — correctly escaped. | — |

---

### mcp-command.js — 357 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 81 | OK | Backdrop click listener properly removed before `innerHTML = ''` | Good cleanup pattern. |
| 263–357 | INFO | `_injectStyles()` creates a `<style>` element once (guarded by ID check). | Good. |

---

### memory-graph.js — 451 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 427 | **HIGH** | **Memory leak:** `ResizeObserver` created in `initMemoryGraph()` but **never disconnected** in `destroyMemoryGraph()`. Each time the Memory tab is visited, a new observer is created and leaks. | Store the observer reference and call `.disconnect()` in `destroyMemoryGraph()`. |
| 431 | LOW | Debounce via `e.target._debounce` property — minor DOM property pollution. | Use a module-level Map or WeakMap instead. |
| 318 | LOW | `graph.nodes.forEach(n => ...)` mutates nodes in-place inside `_searchMemory`. If search is called concurrently, nodes are mutated racy. | Not critical since API calls are sequential per user action. |

---

### settings.js — 1126 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 119 | **HIGH** | **XSS vector:** `onclick="fetchModels('${active}')"` — `active` is user-controlled (provider name from settings). If a provider name contains `'`, it breaks out of the onclick attribute. Example: provider name `foo');alert(1)//` would execute arbitrary JS. | Use `encodeURIComponent()` or pass via `dataset` and use `addEventListener`. |
| 144, 148, 247, 257, 319, 329 | INFO | `onclick` in generated HTML — fieldId/category come from hardcoded schema keys, so currently safe. But fragile if schema is ever dynamic. | Prefer event delegation or `addEventListener`. |
| 984–1071 | LOW | `_delegatesAttached` flag is **never reset** on settings panel destroy/recreate. Since it uses event delegation on the persistent `#settings-body`, it works. But if the element were replaced, delegates would not re-attach. | Add cleanup on settings panel teardown. |
| 352 | LOW | Dynamic import of `memory-graph.js` inside `renderSettings()` with `.catch(() => {})` suppressed. | Log a warning. |

---

### settings-schema.js — 580 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 580 | LOW | `initProviderData()` called at module load. Promise is unhandled (fetch failure is caught internally). | Acceptable, but `console.warn` on failure. |

---

### setup-wizard.js — 298 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 286 | LOW | `window._settingsCache = s` — writes to global state directly, bypassing the state module's `setSettingsCache()`. Fragile. | Use `setSettingsCache()` import instead. |
| 29 | INFO | `wizard._trapFocusHandler` stored on DOM element — properly cleaned up in `hideSetupWizard()`. | Good. |

---

### state.js — 138 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 98–116 | OK | `resetVoiceState()` properly resets all fields, stops audio, closes AudioContext. | Good cleanup. |

---

### tts.js — 228 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 216–228 | LOW | `beforeunload` listener registered at module scope. **Not removable** but acceptable for page-life cleanup. | Good for its purpose. |
| 108–213 | OK | `playTTSAudio()` has proper timeout safety net, `completed` guard against double-fire, and try/catch. | Good error handling. |

---

### utils.js — 156 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 56–63 | OK | `toast.innerHTML` with `escHtml()` — safe. | — |
| 33–82 | LOW | `showToast()` creates a `setTimeout` per toast. If toast is manually dismissed, the timeout still fires (harmless, but attempts to remove already-removed element). | Use a sentinel flag per toast. |

---

### voice.js — 230 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 96–109 | OK | `onend` handler uses `setTimeout` for restart, properly cleared in `stopBrowserSpeechRec()`. | Good cleanup. |
| 190–212 | OK | `initVoiceToggles()` has duplicate-attachment guard (`_voiceToggleListenersAttached`). | Good. |

---

### ws.js — 431 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 62–79 | OK | Heartbeat with interval + timeout — properly managed. | — |
| 147 | LOW | Dynamic import of `api-client.js` **inside `onopen`**. Module caching means it's fine, but style inconsistency. | Prefer static import at top. |
| 298–313 | OK | Stream buffer batching via `requestAnimationFrame` — race-safe because `forEach` on Map iterates a snapshot. | Good pattern. |
| 370–371 | LOW | `avatarRenderer.setMouthOpen(data.value)` — `data.value` could be `undefined`. | Add `?? 0` guard. |

---

## JS Core Files (webui/js/)

---

### app.js — 1056 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 59 | **MEDIUM** | **Memory leak:** `prefersReducedMotion.addEventListener('change', ...)` — listener persists for lifetime. | Store the handler and remove in `beforeunload`. |
| 193–194 | LOW | Nav-item click listeners added on each init (only once per DOMContentLoaded). Fine. | — |
| 197–202 | LOW | `hashchange` listener — never removed. Acceptable. | — |
| 320–333 | LOW | Document keydown for auto-focus — never removed. | — |
| 954–959 | **MEDIUM** | **Memory leak:** `MutationObserver` on `#tab-settings` is **never disconnected**. The observer fires every time the settings panel class changes. If settings tab is hidden/shown many times, the observer accumulates callbacks. | Store the observer and call `.disconnect()` when settings tab is removed or on page unload. |
| 1014 | OK | `_healthInterval` is cleared on `beforeunload`. | Good. |
| 1030–1039 | LOW | `online`/`offline` event listeners never removed. Modest leak. | Clean up on `beforeunload`. |
| 1044–1056 | LOW | **Duplicate `DOMContentLoaded` listener.** The second one (lines 1044–1056) registers only a single input handler, but it adds an unnecessary second entry point. | Merge into main `DOMContentLoaded`. |

---

### avatar.js — 1465 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 4–8 | LOW | `console.warn` monkey-patched globally to suppress THREE deprecation warnings. Side-effect at module scope. | Acceptable, but prefer a local suppression. |
| 22–28 | LOW | Top-level dynamic `import('./advanced-lipsync.js')` with try/catch — runs at module evaluation time. If slow, it blocks execution. | Move to lazy init. |
| 290, 692 | **MEDIUM** | **`console.log` in production code.** Lines 290: `[Avatar] Model loaded successfully`, 692: `Post-processing initialized`. These leak information and create noise in production. | Use `console.debug` or remove. |
| 1359–1464 | OK | `destroy()` is **comprehensive** — cleans up RAF, ResizeObserver, visibility handler, event listeners, timers, VRM/scene objects, audio context, composer, and container. | Excellent cleanup. |
| 157–169 | OK | WebGL context lost/restored handlers — properly stored and cancellable via RAF. | Good. |
| 1286–1309 | OK | `_startIdleBehaviorLoop()` uses `_idleBehaviorTimer` — cleaned up in `destroy()`. | Good. |

---

### animation-manager.js — 469 lines

No issues found. Clean implementation with proper cleanup.

---

### idle-manager.js — 203 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 96–97 | LOW | Directly sets `this._avatar._sleepBlinkOpenSec` — accesses private property of another class. | Add a public setter method. |
| 79–83 | OK | `destroy()` clears all timers. | Good. |

---

### adaptive-lipsync.js — 40 lines

No issues.

---

### advanced-lipsync.js — 175 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 57 | LOW | `console.log('AdvancedLipSync Initialized...')` in production. | Remove or use `console.debug`. |
| 131 | OK | Fallback to `this._lastViseme` for consonant/silence — prevents flickering. | Good. |

---

### viseme-scheduler.js — 132 lines

No issues.

---

### visemes.js — 117 lines

No issues.

---

### i18n.js — 74 lines

No issues.

---

### metrics.js — 116 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 87–108 | OK | `initMetricsAutoRefresh()` with interval + observer. Properly cleaned up on `beforeunload`. | Good. |
| 111–115 | OK | Cleanup on `beforeunload`. | Good. |

---

### swarm.js — 122 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 111–113 | **MEDIUM** | **No destroy/cleanup.** D3 force simulation continues running after leaving the Swarm tab. Each time the tab is visited, a new `SwarmGraph` is created (line 112), but old ones are not cleaned up via `window.swarmGraph`. | Add a `destroy()` method that stops the simulation and cleans up SVG. Call it before creating a new instance. |
| 37–40 | LOW | D3 force simulation runs continuously. When the container is removed from DOM, ticks still fire. | Stop simulation on tab hide. |

---

### audio-utils.js — 132 lines

No issues.

---

### frequency-analyzer.js — 256 lines

No issues.

---

### sprite-avatar.js — 94 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 90–93 | OK | `destroy()` cancels RAF and clears container. | Good. |

---

### vrm-animation.js — 300 lines

No issues.

---

### custom-select.js — 81 lines

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 60–62 | **MEDIUM** | **Document click listener accumulates per select element.** Each `initCustomSelects()` call adds a `click` listener on `document` for every `<select>` element. If `initCustomSelects()` is called multiple times or selects are dynamically added, duplicate listeners pile up. | Use a single delegated click handler on `document` or a flag to prevent duplicate registration. |
| 29 | LOW | `list.innerHTML = ''` then repopulate on every open — minor perf issue for large selects. | OK for typical size. |

---

## CSS (webui/css/style.css)

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| — | LOW | Multiple `@keyframes spin` definitions (lines 1777 and 1015). The second one (injected by JS at app.js:62) overrides or duplicates. | Consolidate into CSS file. |

---

## HTML (webui/index.html)

| Line | Severity | Finding | Fix |
|------|----------|---------|-----|
| 21–22 | LOW | CDN dependency for highlight.js (`cdnjs.cloudflare.com`). App will work without it (code blocks won't highlight), but offline scenarios break. | Consider bundling or caching in service worker. |
| 438–439 | INFO | `d3.min.js` loaded as plain script (not module). Intentional for global access. | OK. |

---

## Cross-cutting Issues

### Console output in production
| File | Line | Severity | Details |
|------|------|----------|---------|
| avatar.js | 290 | MEDIUM | `console.log('[Avatar] Model loaded successfully')` |
| avatar.js | 692 | MEDIUM | `console.log('[Avatar] Post-processing initialized')` |
| advanced-lipsync.js | 57 | LOW | `console.log('[AdvancedLipSync] Initialized...')` |
| app.js | 54 | LOW | `console.log('GPU tier: ...')` |

### Memory Leaks — Active paths
| File | Line | Leak | Severity |
|------|------|------|----------|
| memory-graph.js | 427 | `ResizeObserver` never disconnected | HIGH |
| app.js | 954 | `MutationObserver` on settings tab never disconnected | MEDIUM |
| custom-select.js | 60 | Document click listeners accumulate | MEDIUM |
| app.js | 59 | `prefersReducedMotion` change listener never removed | MEDIUM |
| swarm.js | 111 | D3 simulation continues after tab hide | MEDIUM |

### Missing null/undefined guards
| File | Line | Issue | Severity |
|------|------|-------|----------|
| ws.js | 370–371 | `data.value` could be undefined when calling `setMouthOpen()` | LOW |

### XSS Assessment
The codebase consistently uses `escHtml()` for user data interpolated into HTML. The **one high-risk exception** is:
- **settings.js:119** — `onclick="fetchModels('${active}')"` where `active` is a user-controlled provider name string.

---

## Recommendations (Priority Order)

1. **P0 — Fix XSS in settings.js:119**: Replace the inline `onclick` with `addEventListener` or pass the provider as a `data-` attribute.

2. **P0 — Fix ResizeObserver leak in memory-graph.js:427**: Store the observer and call `.disconnect()` in `destroyMemoryGraph()`.

3. **P1 — Fix MutationObserver leak in app.js:954**: Store the observer and disconnect on cleanup.

4. **P1 — Fix custom-select.js:60**: Use a single delegated document click handler instead of one per `<select>`.

5. **P1 — Fix swarm.js: destroy**: Add cleanup for D3 simulation and proper lifecycle.

6. **P2 — Remove console.log statements** in production paths (avatar.js:290, 692, advanced-lipsync.js:57, app.js:54).

7. **P2 — Add try/catch for `res.json()` in history.js:149**.

8. **P3 — Remove duplicate DOMContentLoaded listener in app.js:1044**.

9. **P3 — Guard `data.value` in ws.js:371** with `?? 0`.

10. **P3 — Refactor inline `onclick` handlers in settings.js** to use `addEventListener` for future-proofing.
