# Amalgam Frontend Module Guide

Documentation for the ES module system in `webui/js/modules/`.

## Overview

The Amalgam frontend is built with vanilla JavaScript ES modules. There is no build step, no bundler, and no npm. All modules are loaded directly by the browser via `<script type="module">`.

The entry point is `webui/js/app.js`, which imports and wires together all modules from `webui/js/modules/`.

## Architecture

```
app.js (orchestrator)
  |
  +-- modules/state.js          (shared mutable state)
  +-- modules/config.js         (URL constants)
  +-- modules/api-client.js     (fetch wrapper)
  +-- modules/ws.js             (WebSocket connection)
  +-- modules/markdown.js       (message rendering)
  +-- modules/settings.js       (settings panel)
  +-- modules/settings-schema.js(settings form definitions)
  +-- modules/tts.js            (TTS queue + audio playback)
  +-- modules/voice.js          (voice input/output)
  +-- modules/history.js        (session history panel)
  +-- modules/mcp.js            (MCP server/tool display)
  +-- modules/mcp-command.js    (interactive /mcp panel)
  +-- modules/health.js         (health bar)
  +-- modules/setup-wizard.js   (first-run wizard)
  +-- modules/utils.js          (shared utilities)
```

**Root-level scripts** (not in `modules/`) handle rendering and animation:

```
app.js            (orchestrator)
avatar.js         (VRM avatar - Three.js)
visemes.js        (viseme mapping definitions)
viseme-scheduler.js (viseme timing)
adaptive-lipsync.js (adaptive lip-sync)
advanced-lipsync.js (advanced lip-sync engine)
vrm-animation.js  (VRM animation loading)
idle-manager.js   (idle animations)
sprite-avatar.js  (2D sprite fallback)
audio-utils.js    (audio analysis)
frequency-analyzer.js (frequency analysis)
custom-select.js  (custom dropdowns)
i18n.js           (internationalization)
metrics.js        (metrics dashboard)
swarm.js          (agent swarm visualization - D3.js)
```

---

## Module Reference

### `modules/state.js`

**Purpose:** Shared mutable application state with getter/setter pairs.

ES module `export let` bindings are live only when accessed via `import * as ns`. Destructured imports capture a snapshot. So this module exports getter/setter pairs instead.

**Key exports:**

| Function | Description |
|---|---|
| `setDomRefs({chatMessages, chatInput, statusDot, statusText})` | Store DOM references during init |
| `getChatMessages()` / `setChatMessages(v)` | Chat message container element |
| `getChatInput()` | Chat input element |
| `getStatusDot()` / `getStatusText()` | Status bar elements |
| `getSettings()` / `setSettingsCache(s)` | Cached settings object |
| `getWs()` / `setWs(v)` | WebSocket instance |
| `getCurrentAssistantMessage()` / `setCurrentAssistantMessage(v)` | Current assistant message element |
| `getLastUserMessage()` / `setLastUserMessage(v)` | Last user message text |
| `getCurrentSessionId()` / `setCurrentSessionId(v)` | Active session ID |
| `getSessionHasMessages()` / `setSessionHasMessages(v)` | Whether session has messages |
| `getAvatarRenderer()` / `setAvatarRenderer(v)` | VRM avatar renderer instance |
| `getAvatarPreviewRenderer()` / `setAvatarPreviewRenderer(v)` | Avatar preview renderer |
| `getSpeakingMsgId()` / `setSpeakingMsgId(v)` | ID of message being spoken by TTS |
| `getIsPlayingTTS()` / `setIsPlayingTTS(v)` | TTS playback state |
| `getVoiceInputEnabled()` / `setVoiceInputEnabled(v)` | Voice input toggle |
| `getVoiceOutputEnabled()` / `setVoiceOutputEnabled(v)` | Voice output toggle |
| `getAudioContext()` / `setAudioContext(v)` | Web Audio API context |
| `getCurrentAudioSource()` / `setCurrentAudioSource(v)` | Current audio source node |
| `getTtsQueue()` / `setTtsQueue(v)` | TTS audio queue array |
| `getTtsQueuePlaying()` / `setTtsQueuePlaying(v)` | Whether TTS queue is playing |
| `getTtsFlushRequested()` / `setTtsFlushRequested(v)` | TTS flush flag |
| `getMcpServersCache()` / `setMcpServersCache(v)` | Cached MCP servers |

---

### `modules/config.js`

**Purpose:** Application constants and URL derivation. Zero dependencies.

**Exports:**

| Export | Type | Description |
|---|---|---|
| `IS_TAURI` | `boolean` | Whether running in Tauri desktop shell |
| `BASE_URL` | `string` | API base URL (`''` for web, `http://localhost:8000` for Tauri) |
| `WS_BASE` | `string` | WebSocket base URL (auto-derived from page location) |

---

### `modules/api-client.js`

**Purpose:** Generic fetch wrapper with timeout/abort. Zero dependencies.

**Export:**

```javascript
export async function api(url, opts = {})
```

- Default timeout: 30 seconds
- Returns parsed JSON or `null` on error
- Handles network errors, non-OK responses, and empty responses

**Usage:**
```javascript
import { api } from './modules/api-client.js';
const data = await api(BASE_URL + '/api/settings');
```

---

### `modules/ws.js`

**Purpose:** WebSocket connection management with reconnection, heartbeat, and message handling.

**Key exports:**

| Function | Description |
|---|---|
| `connectWS()` | Establish WebSocket connection with auto-reconnect |
| `getPendingMessages()` | Get messages queued while disconnected |
| `setWsCallbacks({addMessage, setStatus, loadSession, fetchCommands, loadCharacters, applySettings})` | Register callbacks (called by app.js) |

**Features:**
- Exponential backoff reconnection (500ms to 5000ms)
- Ping/pong heartbeat (30s interval, 10s timeout)
- Companion mode support (`?mode=companion` URL param)
- Automatic message queuing during disconnection

**Message types handled:**
- `chat_start`, `chat_append` - Streaming chat text
- `emotion`, `expression`, `animation` - Avatar control
- `viseme` - Lip-sync
- `voice_state`, `voice_audio` - Voice I/O
- `thinking` - Thinking display
- `tool_call` - Tool call display
- `roleplay` - Roleplay actions
- `permission_request` - Shell permission prompts
- `theme_change` - Theme switching
- `session_id` - Session ID updates
- `tts_interrupt` - TTS interruption
- `error` - Error messages

---

### `modules/markdown.js`

**Purpose:** Markdown rendering and message formatting for chat messages.

**Key exports:**

| Function | Description |
|---|---|
| `stripMarkers(text)` | Remove internal markers (`/**...*/`, `/[[...]]`, `/((...))`) |
| `formatMessage(text)` | Format a message with markdown, code blocks, and tool call display |
| `getMessageHtml(text)` | Get HTML for a message |
| `renderMarkdown(text)` | Render markdown to HTML |
| `_isErrorText(text)` | Check if text is an error message |
| `updateToolCall(id, name, status)` | Update a tool call's display status |

**Supported markdown:**
- Code blocks (fenced with language detection)
- Inline code
- Bold (`**text**`)
- Italic (`*text*`)
- Links (`[text](url)`)
- Tool call blocks (`tool:name|status`)
- Thinking blocks (`thinking:text`)

---

### `modules/settings.js`

**Purpose:** Settings panel rendering, form management, and provider/character list management.

**Key exports:**

| Function | Description |
|---|---|
| `renderSettings()` | Render the full settings panel from schema |
| `renderCategory(cat)` | Render a specific settings category |
| `filterSettings(query)` | Filter settings fields by search query |
| `saveCategory(cat)` | Save all fields in a category |
| `refreshProviderList()` | Fetch and render provider dropdown |
| `refreshCharacterList()` | Fetch and render character dropdown |
| `refreshCharacterInfo(charId)` | Fetch and display character details |
| `testConnection(provider)` | Test LLM provider connection |
| `fetchModels(provider)` | Fetch available models for a provider |
| `toggleFieldVisibility(fieldId)` | Toggle password field visibility |
| `setActiveSettingsTab(tab)` | Switch active settings tab |
| `getActiveSettingsTab()` | Get current settings tab |
| `_attachSettingsDelegates()` | Attach event delegates for settings interactions |

---

### `modules/settings-schema.js`

**Purpose:** Data-driven settings form definitions. Zero dependencies.

Defines the `SETTINGS_SCHEMA` object that drives the settings UI. Each category has an icon and fields with type, key, label, and description.

**Exported constants:**

| Export | Description |
|---|---|
| `PROVIDER_DISPLAY_NAMES` | Map of provider IDs to display names |
| `SETTINGS_SCHEMA` | Complete settings form schema |

**Schema structure:**
```javascript
{
  "Character": {
    icon: "person",
    fields: {
      active_character: {
        label: "Active Character",
        type: "select",
        key: "character.active",
        dynamic_characters: true,
        description: "Which character personality to use"
      }
    }
  }
}
```

**Field types:** `select`, `text`, `password`, `number`, `textarea`, `toggle`, `dynamic_providers`

---

### `modules/tts.js`

**Purpose:** Text-to-Speech queue management and audio playback via Web Audio API.

**Key exports:**

| Function | Description |
|---|---|
| `processTTSQueue()` | Process the next item in the TTS queue |
| `flushTTSQueue()` | Clear and stop all queued TTS audio |
| `setTtsCallbacks({setStatus, updateSpeakButtons})` | Register callbacks (called by app.js) |
| `ensureAudioContext()` | Get or create the Web Audio API context |

**Features:**
- Sentence-level TTS queue for natural conversation flow
- Base64 WAV audio decoding and playback
- Viseme callback for lip-sync during playback
- Automatic queue processing on audio end
- Interrupt support for cancellation

---

### `modules/voice.js`

**Purpose:** Voice input/output management including browser Web Speech API and server-side STT.

**Key exports:**

| Function | Description |
|---|---|
| `isBrowserStt()` | Check if browser Web Speech API is the STT engine |
| `startBrowserSpeechRec()` | Start browser speech recognition |
| `stopBrowserSpeechRec()` | Stop browser speech recognition |
| `initVoiceToggles()` | Initialize voice input/output toggle buttons |
| `updateVoiceState()` | Update voice state UI (recording, speaking, idle) |
| `_applyVoiceInput(enabled)` | Enable/disable voice input |
| `_applyVoiceOutput(enabled)` | Enable/disable voice output |
| `setVoiceStatusCallback(fn)` | Register status update callback |

**Features:**
- Browser Web Speech API for free STT
- Server-side STT via WebSocket commands
- Automatic restart on recognition errors
- Voice toggle UI management
- Wake word integration

---

### `modules/history.js`

**Purpose:** Session history panel UI with search functionality.

**Key exports:**

| Function | Description |
|---|---|
| `loadHistory()` | Fetch and render session list |
| `initHistoryEvents()` | Attach event listeners for history panel |
| `setHistoryDeps({loadSession, showToast})` | Register dependencies (called by app.js) |
| `updateHistoryToggle()` | Show/hide history toggle based on sessions |

**Features:**
- Session list with title, message count, date
- Click to load a session
- Search/filter sessions
- Delete sessions
- Rename sessions inline

---

### `modules/mcp.js`

**Purpose:** MCP server and tool display in the settings panel.

**Key exports:**

| Function | Description |
|---|---|
| `loadMCP()` | Fetch and render MCP servers and tools |

**Renders:**
- Server list with connection status (green/red dot)
- Enable/disable toggle per server
- Tool grid showing all available MCP tools
- Tool name, description, and server origin

---

### `modules/mcp-command.js`

**Purpose:** Interactive `/mcp` slash command panel for toggling MCP servers.

**Key exports:**

| Function | Description |
|---|---|
| `initMcpCommand({onConfirm})` | Initialize the MCP panel |
| `openMcpPanel()` | Open the MCP server toggle overlay |
| `isMcpPanelOpen()` | Check if panel is open |
| `handleMcpKeydown(e)` | Handle keyboard navigation in panel |

**Features:**
- Keyboard-navigable overlay (arrow keys, Space, Enter, Escape)
- Shows all MCP servers with connection status
- Toggle switches per server
- Arrow keys navigate, Space toggles, Enter confirms, Escape cancels

---

### `modules/health.js`

**Purpose:** Health bar management showing service status.

**Key exports:**

| Function | Description |
|---|---|
| `updateHealthBar(services)` | Update health dot indicators from service state |
| `refreshHealth()` | Fetch `/api/health` and update the bar |

**Renders:**
- Small colored dots in the UI header
- Green for `ok`, yellow for `degraded`, red for `down`, gray for `unknown`
- Tooltip with service name, status, and detail

---

### `modules/setup-wizard.js`

**Purpose:** First-run setup wizard with step-by-step configuration.

**Key exports:**

| Function | Description |
|---|---|
| `showSetupWizard()` | Display the setup wizard overlay |

**Steps:**
1. **Welcome** - Choose setup mode (quick/custom)
2. **Provider** - Select and configure LLM provider
3. **Voice** - Configure STT and TTS engines
4. **Character** - Choose a character

**Features:**
- Provider catalog with free tier indicators
- API key validation hints
- Connection testing per provider
- TTS preview
- Focus trapping for accessibility
- Dismissible after first completion

---

### `modules/utils.js`

**Purpose:** Shared utility functions. Zero dependencies.

**Key exports:**

| Function | Description |
|---|---|
| `escapeHtml(str)` / `escHtml(str)` | HTML entity escaping |
| `_getNestedValue(obj, path)` | Get nested object value by dot-notation path |
| `showToast(message, type, options)` | Display a toast notification |
| `applyTheme(theme)` | Apply a UI theme (dark, midnight, light, nord) |
| `applyAccentColor(color)` | Apply accent color CSS variable |
| `detectGPUCapability()` | Detect GPU tier for adaptive quality |
| `trapFocus(element)` | Trap keyboard focus within an element (accessibility) |

**Toast types:** `success`, `danger`, `warning`, `info`, `system`

---

## Additional Scripts (Root Level)

These scripts live in `webui/js/` (not `modules/`) and handle rendering, animation, and visualization.

### `avatar.js`

The main VRM avatar renderer using Three.js and @pixiv/three-vrm. Handles:
- VRM model loading and rendering
- Emotion/expression control
- Lip-sync via viseme mapping
- Post-processing (bloom, output)
- Sprite avatar fallback for low-end GPUs

### `visemes.js`

Defines the 15 viseme shapes used for lip-sync (sil, PP, FF, TH, DD, kk, CH, SS, nn, RR, aa, E, I, O, U).

### `viseme-scheduler.js`

Handles timing of viseme transitions during speech for natural lip movement.

### `adaptive-lipsync.js`

Adaptive lip-sync manager that adjusts viseme intensity based on audio analysis.

### `advanced-lipsync.js`

Advanced lip-sync engine with frequency-based analysis for more realistic mouth movement.

### `vrm-animation.js`

VRM animation loading and playback (VRMA format). Handles animation clips from character directories.

### `idle-manager.js`

Manages idle animations: waiting (30s), sleeping (120s), micro-animations (curiosity, amusement, admiration, confusion).

### `sprite-avatar.js`

2D sprite-based avatar fallback when WebGL/Three.js is not available or GPU is too weak.

### `audio-utils.js`

Audio analysis utilities for frequency analysis and waveform processing.

### `frequency-analyzer.js`

Real-time frequency analysis using Web Audio API AnalyserNode for lip-sync driving.

### `custom-select.js`

Replaces native `<select>` elements with custom styled dropdowns for better UI consistency.

### `i18n.js`

Internationalization system. Loads translation files from `webui/js/locales/`. Supports English (`en`) and Chinese (`zh`).

### `metrics.js`

Metrics dashboard rendering. Fetches summary, turns, and tool history from the API and renders cards and charts.

### `swarm.js`

Agent swarm visualization using D3.js force-directed graph. Renders in the Swarm tab and updates via WebSocket events.

---

## How to Add a New Module

1. **Create the file:** `webui/js/modules/your-module.js`

2. **Export your functions:**
```javascript
// your-module.js
import { BASE_URL } from './config.js';
import { api } from './api-client.js';

export async function doSomething() {
    const data = await api(BASE_URL + '/api/your-endpoint');
    return data;
}
```

3. **Import in app.js:**
```javascript
import { doSomething } from './modules/your-module.js';
```

4. **Wire up in DOMContentLoaded:**
```javascript
document.addEventListener('DOMContentLoaded', async () => {
    // ... existing init code ...
    doSomething();
});
```

### Module Conventions

- **Zero-dependency modules** (`config.js`, `api-client.js`, `settings-schema.js`, `utils.js`) have no imports from other project modules.
- **State is shared** via `state.js` getter/setter pairs, not `export let`.
- **Callbacks break circular deps:** Modules that need callbacks from `app.js` export `setXxxCallbacks()` functions. `app.js` calls these during init.
- **No build step:** All code must be valid ES module syntax supported by modern browsers.
- **No npm dependencies:** Vendor libraries are committed to `webui/vendor/`.

---

## Import Map

The `index.html` uses an import map for vendored libraries:

```html
<script type="importmap">
{
    "imports": {
        "three": "./vendor/three.module.js",
        "three/addons/": "./vendor/",
        "@pixiv/three-vrm": "./vendor/three-vrm.module.min.js"
    }
}
</script>
```

This allows `import * as THREE from 'three'` and `import { VRM } from '@pixiv/three-vrm'` to resolve to vendored files.
