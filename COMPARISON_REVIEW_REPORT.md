# Amalgam Comparison & Review Report

**Date:** 2026-06-22  
**Reviewer:** Jcode Agent  
**Scope:** WebUI vs good chat UIs, TUI vs opencode/claude code, Companion mode deep review

---

## AREA 1: WebUI Comparison (vs ChatGPT Web, Amica, etc.)

### 1.1 Input Handling

| Feature | Status | Notes |
|---------|--------|-------|
| Multi-line input | ✅ | Textarea with `rows="1"`, auto-resize up to 120px |
| Shift+Enter for newline | ❓ | Not explicitly handled; default textarea behavior |
| Enter to send | ✅ | Via `send-btn` click handler |
| Image upload | ✅ | File input triggered by image button, preview with remove |
| Image paste | ❌ | Not implemented |
| MCP command panel | ✅ | `/mcp` with keyboard-navigable overlay (Arrow keys, Space, Enter, Escape) |
| Slash commands | ✅ | In chat input via WebSocket `slash_command` type |
| Auto-focus on typing | ✅ | `keydown` listener focuses input when not in a form field |

**Gap:** No drag-and-drop file upload, no image paste handling, no voice message recording UI (voice toggle exists but mic is just on/off).

### 1.2 Message Display

| Feature | Status | Notes |
|---------|--------|-------|
| Markdown rendering | ✅ | **bold**, *italic*, `code`, ```code blocks```, links |
| Code syntax highlighting | ❌ | Just `<pre><code>` with language class — no highlight.js/prism |
| Code block copy button | ❌ | Not implemented |
| Inline code | ✅ | Rendered with `<code>` tags |
| Thinking blocks | ✅ | Collapsible `<details>` with preview |
| Tool call cards | ✅ | Status indicators (running/completed/errored/retrying) |
| Timestamps | ❌ | **Not shown on any message** |
| Role coloring | ✅ | user/accent, assistant/card, system/italic, tool/border |
| Companion messages | ✅ | Distinct gradient + 💚 emoji marker |
| Error messages | ✅ | `msg-error` class with red styling |

**Gaps:** No timestamps, no code syntax highlighting, no code block copy button, no message reactions.

### 1.3 Settings UX

| Feature | Status | Notes |
|---------|--------|-------|
| Categorized sidebar | ✅ | Character, Provider, Voice, UI, Agent, Advanced, Memory, Vault, Rules, etc. |
| Search in settings | ✅ | Filters fields dynamically |
| Auto-save on change | ✅ | Changes saved via batch API without explicit Save button |
| Save feedback | ✅ | Toast notifications |
| Test connection | ✅ | Button in provider settings |
| Fetch models | ✅ | Cloud sync button fetches live model list |
| Field visibility | ✅ | `show_if` conditions for provider-specific fields |
| Dynamic provider config | ✅ | API key, model, base URL per provider |
| Schema-driven | ✅ | Defined in `settings-schema.js` |
| Reset to defaults | ❌ | Not implemented |

**Gaps:** No "Reset to defaults" for individual fields or whole category.

### 1.4 Theme System

| Feature | Status | Notes |
|---------|--------|-------|
| Dark/Light toggle | ✅ | Via `/theme` slash command only |
| Multiple themes | ✅ | 4 themes: dark, midnight, light, nord |
| CSS custom properties | ✅ | All colors via `--var` |
| Accent color picker | ✅ | Custom accent color via color swatches |
| Theme persistence | ✅ | Saved to backend settings |
| OS preference detection | ✅ | `prefers-color-scheme` meta tags for theme-color |
| Reduced motion support | ✅ | `prefers-reduced-motion` media query |

**Gap:** No in-UI theme switcher button (only via slash command or settings panel).

### 1.5 Responsiveness

| Feature | Status | Notes |
|---------|--------|-------|
| Mobile tab bar | ✅ | Bottom navigation duplicate of sidebar |
| Viewport meta | ✅ | `width=device-width, viewport-fit=cover` |
| Touch targets | ✅ | 32px minimum for icon buttons |
| Message max-width | ✅ | `max-width: 80%` |
| History panel | ✅ | Slide-out panel, 320px wide |
| PWA support | ✅ | Manifest, service worker, apple-mobile-web-app |
| Landscape support | ✅ | Flexbox layout adapts |

**Gap:** No dedicated mobile chat input optimization (keyboard avoidance, etc.).

### 1.6 Accessibility

| Feature | Status | Notes |
|---------|--------|-------|
| ARIA labels | ✅ | Most interactive elements have `aria-label` |
| Skip-to-content | ✅ | First focusable element |
| Role="log" on messages | ✅ | `aria-live="polite"` |
| Focus management | ✅ | Setup wizard, settings, MCP panel |
| Tab trapping | ✅ | In modal dialogs via `trapFocus()` |
| Keyboard navigation | ✅ | Tab through all controls, Arrow keys in MCP panel |
| Color contrast | ✅ | Defined color palette with good contrast |
| Screen reader status | ✅ | Status dot updates, offline bar `role="alert"` |

**Minor gaps:** Chat messages don't auto-focus new messages. Toast container `aria-live="polite"` but no `role="alert"` for critical toasts.

### 1.7 Animations

| Feature | Status | Notes |
|---------|--------|-------|
| Message appear | ❌ | No transition/animation on new messages |
| Thinking dots | ✅ | Animated dots during assistant thinking |
| Voice bars | ✅ | Animated equalizer during speech |
| Toast in/out | ✅ | Slide-in + fade-out animations |
| Tab transitions | ❌ | Instant tab switching |
| Avatar state transitions | ✅ | Border color changes for thinking/speaking/listening/typing |
| Health bar | ✅ | Color transitions |

**Gap:** No message appear animation, no smooth scroll to new messages.

### 1.8 Message Actions

| Feature | Status | Notes |
|---------|--------|-------|
| Copy message | ✅ | Copies text content to clipboard |
| Edit message | ✅ | Puts content back in input with edit target |
| Regenerate | ✅ | Removes user+assistant message pair, resends |
| Speak/Stop TTS | ✅ | Sends to TTS engine |
| Delete message | ❌ | **Not implemented** |
| Message timestamp | ❌ | **Not shown** |
| Copy code block | ❌ | No per-block copy button |

---

## AREA 2: TUI Comparison (vs opencode & claude code)

### 2.1 Slash Commands

| Command | Status | Notes |
|---------|--------|-------|
| `/help` | ✅ | Rich table display with descriptions |
| `/model` | ✅ | Inline dropdown with fuzzy filter + live fetch |
| `/provider` | ✅ | Sub-commands: add, set, rm with auto-complete |
| `/clear` | ✅ | Clears display |
| `/new` | ✅ | New session |
| `/think` | ✅ | Toggle thinking display |
| `/rename` | ✅ | Rename current session |
| `/resume` | ✅ | Shows last 5 turns |
| `/compact` | ✅ | Force memory compaction |
| `/health` | ✅ | Live service health checks with table |
| `/companion` | ✅ | Toggle companion mode |
| `/settings` | ✅ | View/set settings keys with auto-complete |
| `/memory` | ✅ | Session/message stats |
| `/stats` | ✅ | Cost, tokens, latency, tool calls |
| `/theme` | ✅ | 4 themes with dropdown |
| `/character` | ✅ | Switch character with directory listing |
| `/profile` | ✅ | Switch profile (4 profiles) |
| `/permission` | ✅ | Set MCP permission level |

**Gap vs opencode:** OpenCode supports `/search` for semantic search, `/edit` for file editing, `/context` for context attachment — none of these exist in Amalgam TUI.

### 2.2 Keyboard Shortcuts

| Shortcut | Status | Notes |
|----------|--------|-------|
| Ctrl+Q / Ctrl+D | ✅ | Quit |
| Ctrl+N | ✅ | New session |
| Ctrl+L | ✅ | Clear screen |
| Escape | ✅ | Cancel/hide dropdown, cancel stream |
| Up/Down | ✅ | Navigate inline dropdown |
| Ctrl+E (edit) | ❌ | Not implemented |
| Ctrl+D (diff) | ❌ | Not applicable (no file editing) |
| Ctrl+P (file picker) | ❌ | Not implemented |

### 2.3 Syntax Highlighting & Rendering

| Feature | Status | Notes |
|---------|--------|-------|
| Markdown rendering | ✅ | Via Rich `Markdown` widget |
| Code theme | ✅ | Nord code theme (configurable) |
| Syntax highlighting | ✅ | Via Rich `Syntax` |
| Role labels | ✅ | Color-coded labels: User, Assistant, Tool, Error, Think, System, etc. |
| Thinking blocks | ❌ | Not collapsible in TUI |
| Tool call display | ❌ | No structured tool card display |

**TUI rendering is solid** — Rich library provides good markdown rendering with code highlighting. Better than most terminal chat UIs.

### 2.4 File Picker / Context Attachment

| Feature | Status | Notes |
|---------|--------|-------|
| File picker | ❌ | Not implemented |
| Context attachment | ❌ | Not implemented |
| Vault access | ❌ | Not exposed in TUI |

**Major gap** vs opencode which supports file/folder drag-drop and context attachment. Amalgam TUI is chat-only.

### 2.5 Model Switching Inline

| Feature | Status | Notes |
|---------|--------|-------|
| Inline model switch | ✅ | `/model` with live fetch from API + fallback |
| Provider switch | ✅ | `/provider` with add/set/rm sub-commands |
| API key management | ✅ | Inline password input for API keys |
| Model auto-complete | ✅ | Fuzzy filter on model names |

**This is well done** — better than many TUIs which require leaving the app.

### 2.6 Split Panes

| Feature | Status | Notes |
|---------|--------|-------|
| Split panes | ❌ | **Not implemented** |
| History sidebar | ❌ | Not available in TUI |
| Session list | ❌ | `/memory` shows stats only |
| Search history | ❌ | Not available |

**Gap:** No history or session browser in TUI.

### 2.7 Search History

| Feature | Status | Notes |
|---------|--------|-------|
| Search all conversations | ❌ | Not implemented in TUI |
| `/resume` | ✅ | Shows last 5 turns of current session |

### 2.8 Session Management

| Feature | Status | Notes |
|---------|--------|-------|
| New session | ✅ | `/new` |
| Rename session | ✅ | `/rename` |
| List sessions | ❌ | `/memory` shows count only |
| Delete session | ❌ | Not implemented |
| Export session | ❌ | Not implemented |
| Clear all history | ❌ | Not implemented in TUI |

### 2.9 Cost/Token Display

| Feature | Status | Notes |
|---------|--------|-------|
| Cost display | ✅ | `/stats` shows USD cost |
| Token count | ✅ | Total tokens in stats |
| Latency | ✅ | Avg latency in ms |
| Tool calls | ✅ | Total tool call count |
| Header stats | ✅ | Message count, character count, session ID, provider/model |

**Well implemented** — better than many competitors.

### 2.10 Auto-scroll + Follow Mode

| Feature | Status | Notes |
|---------|--------|-------|
| Auto-scroll | ✅ | RichLog auto-scrolls by default |
| Follow mode toggle | ❌ | No unfollow/follow toggle |
| Stream area | ✅ | Dedicated area for streaming chunks below chat |

### 2.11 Error Recovery

| Feature | Status | Notes |
|---------|--------|-------|
| Loading overlay | ✅ | Spinner + message during initialization |
| Backend failure | ✅ | Shows error message, placeholder input |
| Error display | ✅ | Truncated stack traces, colored error output |
| Stream cancellation | ✅ | Escape to cancel streaming |
| Graceful degradation | ✅ | Works with or without backend features |

### 2.12 TUI Summary

**Strengths:**
- Rich markdown + syntax highlighting (better than many competitors)
- Comprehensive slash command system with fuzzy-filtered inline dropdown
- Inline API key entry (password masked)
- Cost/token analytics
- 4 theme palettes with live switching
- Good error handling

**Weaknesses vs opencode/claude code:**
- No split panes or history sidebar
- No file picker or context attachment
- No search across conversations
- No `/edit`, `/search` commands
- No session list/delete/export
- No follow-mode toggle

---

## AREA 3: Companion Mode Deep Review

### 3.1 Architecture Overview

```
┌────────────────────────┐     idle_enter/idle_exit      ┌──────────────────────┐
│   WebUI (companion.js) │ ──────────────────────────►   │  WS Handler          │
│   • Idle detection     │     WebSocket messages         │  (handler.py)        │
│   • Sends events       │                                │                      │
└────────────────────────┘                                │  CompanionEvent ──►  │
                                                          │                      │
┌────────────────────────┐     POST /api/companion/*      │  CompanionScheduler  │
│   Settings UI          │ ──────────────────────────►   │  (scheduler.py)      │
│   • Toggle on/off      │     REST API calls             │  • Background loop   │
│   • Config parameters  │                                │  • LLM generation    │
│   • Personality notes  │                                │  • WS push           │
└────────────────────────┘                                └──────────────────────┘
                                                                    │
                                                          CompanionEvent
                                                          (events.py)
```

### 3.2 Detailed Q&A

#### Q1: Can companion be toggled on/off from settings? Actually verified?

**YES — verified end-to-end:**

1. **Settings UI:** `settings-schema.js` lines 71-76 defines `companion_enabled` as a toggle with key `companion.enabled` under the Character category.
2. **Frontend live update:** `companion.js` `updateCompanionSettings()` reacts to settings changes — starts/stops idle tracking, sends `idle_exit` if currently disabled mid-idle.
3. **Slash command:** `/companion` toggles via WebSocket (`handler.py` lines 742-748).
4. **REST API:** `POST /api/companion/settings` accepts `{"enabled": true/false}`.
5. **Backend enforcement:** `CompanionScheduler._enabled()` checks `companion.enabled` config at the top of `on_event()` and in every loop iteration (every 30s).

**Toggle is immediate** — no restart required.

#### Q2: What triggers companion messages?

| Trigger | Context Label | Description | Delay |
|---------|--------------|-------------|-------|
| **User joins** | `user_joined` | User opens app/connects | 2 seconds |
| **Idle check-in** | `idle_check_in` | After `idle_check_delay` min of inactivity (default 10) | Configurable |
| **Welcome back** | `welcome_back` | User returns from idle | 1 second |
| **Time change** | `time_change` | Hour boundary crossed (if time_awareness enabled) | Immediate |
| **Manual trigger** | `user_requested` | `POST /api/companion/trigger` or `trigger_now()` | Immediate |
| **Avatar idle prompt** | `idle_prompt_request` | Avatar system requests idle prompt | Immediate |

The background loop runs every 30 seconds and checks all conditions.

#### Q3: What happens if LLM fails during companion message?

**Graceful degradation chain:**
1. `_generate_companion_text()` wraps LLM call in try/except — catches all exceptions, logs warning, returns `None`.
2. `_generate_and_send()` checks if text is falsy — returns `None` early without sending.
3. `trigger_now()` API returns `{"ok": False, "error": "Failed to generate companion message"}`.
4. No retry mechanism exists.
5. The scheduler loop continues unaffected — failure is isolated per message.

**No crash, no unhandled exception, no user-facing error** (companion message just doesn't appear).

#### Q4: Does companion know conversation context? Or is it starting fresh?

**Starts completely fresh.** `_build_companion_prompt()` creates a brand-new prompt from scratch:
- A warm/caring system prompt (hardcoded)
- Personality notes from settings (if configured)
- Time context (date, day, time of day)
- Trigger-specific context instructions
- **No conversation history is fetched or injected**
- **No memory or previous messages are referenced**

The companion has no awareness of what was discussed before. Each message is generated in isolation.

**This is a significant limitation** — the companion cannot reference previous interactions, learn user preferences, or maintain continuity.

#### Q5: Are companion messages distinguishable from user messages in history?

**YES — fully distinguishable:**

- **WebSocket type:** Backend sends `{"type": "companion", "content": "...", "context": "..."}` (vs `{"type": "chat_append"}` for normal messages).
- **CSS class:** Frontend adds `msg-companion` class to the message element (`ws.js` line 416).
- **Visual indicator:** CSS `::before` pseudo-element renders a 💚 emoji (`style.css` lines 265-271).
- **Distinct styling:** Gradient background `linear-gradient(135deg, rgba(129, 199, 132, 0.12), rgba(100, 181, 246, 0.12))` with green border.
- **Context metadata:** `data-companion-context` attribute stores the trigger reason.
- **Not saved to session history:** Companion messages are displayed in chat but there's no evidence they're persisted in memory/session storage.

#### Q6: Can user disable companion mid-conversation?

**YES:**

1. **Settings toggle:** Changing `companion.enabled` from settings triggers `updateCompanionSettings()` which:
   - Stops idle tracking event listeners
   - Clears the idle timer
   - Sends `idle_exit` WebSocket message if currently idle
   
2. **Slash command:** `/companion` toggles immediately via WebSocket handler.

3. **Backend respects toggle:** `CompanionScheduler._enabled()` is checked:
   - At the start of every `on_event()` call
   - At the start of every loop iteration (every 30s)
   - No companion message is generated or sent when disabled

4. **Active companion message:** If an LLM generation is in-flight when disabled, the message will still be sent (generation completes before the disable check). Subsequent triggers will be blocked.

#### Q7: Is there a companion personality prompt that's configurable?

**YES — configurable:**

- **Field:** `companion_personality_notes` in settings (textarea, Character category).
- **Config key:** `companion.personality_notes`
- **Usage:** Appended to system prompt in `_build_companion_prompt()` (line 216): `f"Your personality notes: {personality}"`
- **Default system prompt** (hardcoded, lines 210-228):
  ```
  You are a warm, caring companion living inside a VRM avatar chat app. ...
  RULES:
  - Keep messages short (1-3 sentences) and natural.
  - Never sound robotic or like a customer service bot.
  - Use casual, warm language. You can use emoji sparingly.
  - ...
  ```

The personality notes are supplementary — the core personality is hardcoded in Python.

#### Q8: What edge cases exist?

| Edge Case | Behavior | Severity |
|-----------|----------|----------|
| **Rapid idle enter/exit** | Multiple `idle_enter`/`idle_exit` in quick succession. State flags prevent concurrent welcome-backs but fire-and-forget tasks could stack. | 🟡 Medium — could cause multiple companion messages |
| **Connection drop** | Session unregistered from scheduler on disconnect. Messages won't send. No queuing. | 🟢 Low — silent degradation |
| **Concurrent companion + user message** | Companion generates via `asyncio.create_task` while user message processing is ongoing. No interleaving protection. | 🟡 Medium — companion message may appear before/after user message out of order |
| **Settings change while idle** | Disabling companion sends `idle_exit` immediately. Enabling restarts idle timer from scratch. | 🟢 Low — correct behavior |
| **LLM failure** | Silently fails, returns None. No retry. User unaware. | 🟢 Low — companion message just doesn't appear |
| **Time-change storm** | Hour boundary fires for each connected session simultaneously. Could cause burst of LLM calls. | 🟡 Medium — potential rate limit hit |
| **Multiple tabs/sessions** | Each session has independent idle tracking but shares scheduler. Independent operation. | 🟢 Low — correct isolation |
| **Frontend/backend timer mismatch** | Frontend uses 50% of configured delay (min 1 min) to pre-emptively send idle_enter before backend check-in fires. | 🟢 Low — intentional design |
| **No rate limiting** | Proactive interval can be as low as 10 min, time-change every hour, no minimum gap enforcement (except 5 min for time-change). | 🟡 Medium — could cause companion spam |
| **No conversation context** | Companion has no memory of previous interactions — each message is isolated. | 🔴 High — feels repetitive/robotic |
| **Companion messages not persisted** | No evidence companion messages are saved to session history. | 🟡 Medium — companion "forgets" its own previous messages |

### 3.3 Companion Settings Schema

| Setting | Key | Type | Default | Description |
|---------|-----|------|---------|-------------|
| Enabled | `companion.enabled` | toggle | false | Master toggle |
| Idle Check-In Delay | `companion.idle_check_delay` | number (min) | 10 | Minutes of inactivity before check-in |
| Proactive Interval | `companion.proactive_interval` | number (min) | 60 | Minutes between time-aware messages |
| Time Awareness | `companion.time_awareness` | toggle | true | Send messages acknowledging time of day |
| Personality Notes | `companion.personality_notes` | textarea | "" | Extra personality instructions |

### 3.4 File Coverage

All companion-related files reviewed:
- `backend/core/companion/__init__.py` — Package export (CompanionEvent, CompanionScheduler)
- `backend/core/companion/events.py` — CompanionEventType enum (7 event types) + CompanionEvent dataclass
- `backend/core/companion/scheduler.py` — Full scheduler with prompt building, LLM generation, WS push
- `backend/core/deps.py` — Singleton initialization (lines 95-100)
- `backend/api/routes/companion.py` — REST endpoints: GET/POST /api/companion/settings, POST /api/companion/trigger
- `backend/api/ws/handler.py` — WebSocket event handlers for idle_enter/idle_exit, companion toggle, session register/unregister
- `backend/app.py` — Scheduler start on startup, stop on shutdown (lines 207-234)
- `webui/js/modules/companion.js` — Frontend idle detection, event sending, settings reactivity
- `webui/js/modules/settings-schema.js` — Companion settings fields definition
- `webui/js/modules/ws.js` — Companion message handler (line 412-419), companion mode detection (lines 58-60)
- `webui/css/style.css` — `.msg-companion` styling with gradient + emoji (lines 254-271)
- `cli/companion.py` — CLI companion mode with slash commands, idle loop, wake/sleep states

---

## Key Findings Summary

### WebUI
**Well done:** Message actions (copy/edit/regenerate/speak), thinking blocks, tool call cards, settings schema, accessibility basics, PWA support, theme system.
**Needs improvement:** No timestamps, no code syntax highlighting, no code block copy, no message delete, no file drag-drop/paste, no message appear animations.

### TUI
**Well done:** Rich markdown + syntax highlighting, comprehensive slash commands with fuzzy-filtered inline dropdown, cost/token analytics, inline API key management, 4 themes, good error recovery.
**Needs improvement:** No split panes/history sidebar, no file picker/context attachment, no conversation search, no session list/delete/export, no follow-mode toggle, no `/edit` or `/search` commands.

### Companion Mode
**Well done:** Clean architecture with event system, graceful LLM failure handling, fully toggleable mid-conversation, configurable personality/prompt, visually distinct messages, multiple trigger mechanisms.
**Needs improvement:** No conversation context awareness (each message is generated fresh), no companion message persistence in history, no rate limiting for proactive messages, no retry on LLM failure, potential race conditions with rapid idle toggling.
