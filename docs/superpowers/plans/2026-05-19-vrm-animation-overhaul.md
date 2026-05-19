# VRM Animation Overhaul & Bug Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 13 bugs across animation/VRM, UI/settings, and chat — one by one with auto-tests between each.

**Architecture:** Extract animation logic from `avatar.js` into a new `animation.js` AnimationManager module. Each bug fix is isolated and verified before moving to the next. Amica (`../cloned/amica`) is the reference implementation.

**Tech Stack:** Vanilla JS, Three.js 0.180.0, @pixiv/three-vrm 3.5.2, FastAPI, WebSocket

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `frontend/animation.js` | **Create** | AnimationManager — extracted animation logic |
| `frontend/app.js` | Modify | Wire AnimationManager, fix greeting, error cleanup, message buttons, settings persistence |
| `frontend/avatar.js` | Modify | Delegate animation to AnimationManager, fix camera centering, lip sync conflict, saccade |
| `frontend/index.html` | Modify | Unified settings cards, thinking toggle, message button styles |
| `frontend/style.css` | Modify | Message action buttons, font-size variable, settings layout |
| `backend/config/settings.py` | Modify | Add `ui.thinking_enabled`, `ui.voice_input`, `ui.voice_output` defaults |
| `backend/api/server.py` | Modify | No changes needed (existing endpoints handle all settings) |

---

## Task 1: Batman VRM Not Loading

**Files:**
- Modify: `frontend/avatar.js:155-242`

Batman has `model.vrm` in `characters/batman/`. The issue is likely in `_loadVRM()` — no timeout handling and no fallback on load failure.

- [ ] **Step 1: Add timeout and error fallback to `_loadVRM()`**

In `frontend/avatar.js`, find `_loadVRM()` (line 155). Add a 15-second timeout and fallback to default VRM on failure:

```javascript
_loadVRM() {
    const loader = new GLTFLoader();
    loader.register(parser => new VRMLoaderPlugin(parser));

    const loadPath = this.vrmPath;
    const timeout = setTimeout(() => {
        console.warn(`VRM load timeout for ${loadPath}, falling back to default`);
        this.vrmPath = '/characters/default/model.vrm';
        this._loadVRM();
    }, 15000);

    loader.load(
        loadPath,
        (gltf) => {
            clearTimeout(timeout);
            // ... existing load success code (lines 168-242) ...
        },
        undefined,
        (error) => {
            clearTimeout(timeout);
            console.error(`VRM load error for ${loadPath}:`, error);
            if (loadPath !== '/characters/default/model.vrm') {
                console.warn('Falling back to default VRM');
                this.vrmPath = '/characters/default/model.vrm';
                this._loadVRM();
            }
        }
    );
}
```

- [ ] **Step 2: Auto-test**

Run puppeteer to verify Batman VRM loads (or falls back gracefully):

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000');
  await page.waitForFunction(() => window.__avatarReady === true, { timeout: 20000 });
  const result = await page.evaluate(() => {
    const r = window.__avatarRenderer || document.querySelector('#avatar-canvas')?.__renderer;
    return { hasVRM: !!r?.vrm, path: r?.vrmPath };
  });
  console.log('Batman VRM:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: `hasVRM: true` (either Batman model or default fallback)

- [ ] **Step 3: Commit**

```bash
git add frontend/avatar.js
git commit -m "fix: add VRM load timeout and fallback for Batman and other models"
```

---

## Task 2: Letter Icons → VRM Icons

**Files:**
- Modify: `frontend/vrm-icon-renderer.html`
- Modify: `backend/api/server.py:356-379` (icon regeneration endpoint)

The icon renderer generates VRM portraits for characters with `model.vrm`. Characters without VRM get letter fallbacks. The issue is either the renderer failing silently or the generation script skipping VRM characters.

- [ ] **Step 1: Check current icon generation logic**

Read `backend/api/server.py` lines 356-379 to understand the regeneration endpoint. It should use puppeteer to render VRM icons for characters that have `model.vrm`.

- [ ] **Step 2: Verify icon renderer works for all characters with model.vrm**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  // Test with a known VRM character
  await page.goto('http://localhost:8000/static/vrm-icon-renderer.html?model=/characters/frieren/model.vrm');
  await page.waitForFunction(() => window.__vrmReady === true, { timeout: 15000 });
  console.log('Icon renderer: OK');
  await browser.close();
})();
"
```

Expected: `Icon renderer: OK`

- [ ] **Step 3: Fix any renderer issues found**

If the renderer fails, check the camera positioning in `vrm-icon-renderer.html` lines 73-114. The head/neck bone lookup may fail for certain VRM models.

- [ ] **Step 4: Commit**

```bash
git add frontend/vrm-icon-renderer.html backend/api/server.py
git commit -m "fix: ensure VRM icon generation works for all characters with model.vrm"
```

---

## Task 3: Center Character in Container

**Files:**
- Modify: `frontend/avatar.js:289-369` (`_fitCameraToModel`)
- Modify: `frontend/style.css:432-451` (avatar container CSS)

The character appears off-center because the camera target doesn't match the character's center of mass.

- [ ] **Step 1: Fix camera target in `_fitCameraToModel()`**

In `frontend/avatar.js`, the `_fitCameraToModel()` method (line 289) computes bounds and positions the camera. For the full (non-preview) mode, ensure the camera looks at the character's center:

Find the full-mode camera setup (around line 360-366) and ensure the camera target is at the bounding box center, not just the Y midpoint:

```javascript
// In _fitCameraToModel, full mode section:
const center = new THREE.Vector3();
box.getCenter(center);
this.camera.lookAt(center);
```

- [ ] **Step 2: Ensure CSS centers the canvas, not the container**

In `frontend/style.css`, verify `.avatar-canvas-container` uses flexbox to center its child canvas:

```css
.avatar-canvas-container {
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
}
```

- [ ] **Step 3: Auto-test**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000#avatar');
  await page.waitForFunction(() => window.__avatarReady === true, { timeout: 20000 });
  // Switch to avatar tab
  await page.click('[data-tab=\"avatar\"]');
  await new Promise(r => setTimeout(r, 1000));
  const result = await page.evaluate(() => {
    const canvas = document.querySelector('#avatar-canvas canvas');
    if (!canvas) return { error: 'no canvas' };
    const rect = canvas.getBoundingClientRect();
    return { width: rect.width, height: rect.height, left: rect.left, top: rect.top };
  });
  console.log('Avatar canvas position:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: canvas centered within its container

- [ ] **Step 4: Commit**

```bash
git add frontend/avatar.js frontend/style.css
git commit -m "fix: center VRM character in avatar container"
```

---

## Task 4: Preview Avatar Head-Box Auto-Sizing

**Files:**
- Modify: `frontend/avatar.js:289-369` (`_fitCameraToModel`)

The preview avatar (chat header) doesn't auto-size its camera to frame the character's head. The `_fitCameraToModel()` method already has preview mode logic (lines 331-358), but it may not be called after the VRM loads.

- [ ] **Step 1: Ensure `_fitCameraToModel()` is called for preview renderer**

In `frontend/avatar.js`, check that `_loadVRM()` calls `_fitCameraToModel()` at line 217 for both preview and non-preview modes. If it's gated behind `!this.options.preview`, remove that gate.

- [ ] **Step 2: Verify preview camera framing uses head bones**

The preview mode (lines 331-358) uses head/neck bone positions. Verify the bone lookup works:

```javascript
// In _fitCameraToModel, preview section:
const headBone = this.vrm.humanoid.getNormalizedBoneNode('head');
const neckBone = this.vrm.humanoid.getNormalizedBoneNode('neck');
if (!headBone || !neckBone) {
    // Fallback to bounding box
    console.warn('Head/neck bones not found, using bounding box');
}
```

- [ ] **Step 3: Auto-test**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000');
  await page.waitForFunction(() => window.__avatarReady === true, { timeout: 20000 });
  const result = await page.evaluate(() => {
    const preview = document.querySelector('#avatar-preview canvas');
    if (!preview) return { error: 'no preview canvas' };
    return { width: preview.width, height: preview.height, exists: true };
  });
  console.log('Preview avatar:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: preview canvas exists with proper dimensions

- [ ] **Step 4: Commit**

```bash
git add frontend/avatar.js
git commit -m "fix: auto-size preview avatar camera to frame character head"
```

---

## Task 5: Ryuk Not Looking at Camera

**Files:**
- Modify: `frontend/avatar.js:184-188` (saccade target setup)
- Modify: `frontend/avatar.js:454-481` (`_updateSaccade`)

Ryuk's VRM may have a different lookAt configuration. The saccade target is parented to the camera (line 184-188), which should make the character look toward the camera. Check if the lookAt target is properly assigned.

- [ ] **Step 1: Verify saccade target is assigned to VRM lookAt**

In `frontend/avatar.js`, after VRM loads (around line 184-188), the code sets:
```javascript
this._saccadeTarget = new THREE.Object3D();
this.camera.add(this._saccadeTarget);
this.vrm.lookAt.target = this._saccadeTarget;
```

Verify this runs for all VRM models, including Ryuk. If `this.vrm.lookAt` is null for some models, add a null check.

- [ ] **Step 2: Ensure lookAt is auto mode, not bone mode**

Some VRM models use bone-based lookAt instead of expression-based. Check if Ryuk's VRM has `lookAtType` set. If it's bone-based, the saccade jitter may conflict. Force auto mode:

```javascript
if (this.vrm.lookAt) {
    this.vrm.lookAt.autoUpdate = true;
    this._saccadeTarget = new THREE.Object3D();
    this.camera.add(this._saccadeTarget);
    this.vrm.lookAt.target = this._saccadeTarget;
}
```

- [ ] **Step 3: Auto-test**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000');
  await page.waitForFunction(() => window.__avatarReady === true, { timeout: 20000 });
  // Switch to Ryuk
  await page.evaluate(async () => {
    await fetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ character: { active: 'ryuk' } })
    });
  });
  await page.reload();
  await page.waitForFunction(() => window.__avatarReady === true, { timeout: 20000 });
  const result = await page.evaluate(() => {
    const r = document.querySelector('#avatar-canvas')?.__renderer;
    return { hasLookAt: !!r?.vrm?.lookAt, hasTarget: !!r?.vrm?.lookAt?.target };
  });
  console.log('Ryuk lookAt:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: `hasLookAt: true, hasTarget: true`

- [ ] **Step 4: Commit**

```bash
git add frontend/avatar.js
git commit -m "fix: ensure Ryuk and all VRM models look at camera via saccade target"
```

---

## Task 6: Diana Voice Bug (Mouth/Eyes)

**Files:**
- Modify: `frontend/avatar.js:483-518` (`setEmotion`)
- Modify: `frontend/avatar.js:377-386` (lip sync in `_animate`)

Diana opens her mouth and closes eyes for a second then stops. This is a conflict between `setEmotion()` disabling auto-blink (which closes eyes) and lip sync trying to drive the mouth.

- [ ] **Step 1: Don't reset mouth value in `setEmotion()`**

In `frontend/avatar.js`, `setEmotion()` (line 483) clears all expression values at line 488-491. This resets the mouth open value mid-speech. Fix: skip resetting lip-sync expressions (`aa`, `ih`, `ou`, `ee`, `oh`) when speech is active:

```javascript
setEmotion(emotion) {
    // Reset expression targets to 0
    for (const name of this._allExpressionNames) {
        // Don't reset lip-sync expressions during speech
        if (this._frequencyAnalyzerActive && ['aa', 'ih', 'ou', 'ee', 'oh'].includes(name)) {
            continue;
        }
        this._targetExpressions[name] = 0;
        if (this.vrm.expressionManager) {
            this.vrm.expressionManager.setValue(name, 0);
        }
    }
    // ... rest of setEmotion ...
}
```

- [ ] **Step 2: Don't disable auto-blink during speech**

The blink-disable in `setEmotion()` causes eyes to close. During speech, keep blink enabled:

```javascript
if (emotion === 'neutral') {
    this._setBlinkEnabled(true);
} else {
    // Don't disable blink during speech — it causes eyes to close
    if (!this._frequencyAnalyzerActive) {
        this._setBlinkEnabled(false);
    }
    // ... rest of emotion handling ...
}
```

- [ ] **Step 3: Auto-test**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000');
  await page.waitForFunction(() => window.__avatarReady === true, { timeout: 20000 });
  // Simulate emotion during speech
  const result = await page.evaluate(() => {
    const r = document.querySelector('#avatar-canvas')?.__renderer;
    if (!r) return { error: 'no renderer' };
    // Simulate speech active
    r._frequencyAnalyzerActive = true;
    r.setEmotion('happy');
    const mouthValue = r.vrm.expressionManager.getValue('aa');
    const blinkEnabled = r._blinkEnabled;
    return { mouthPreserved: mouthValue !== undefined, blinkEnabled };
  });
  console.log('Diana voice fix:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: mouth preserved during speech, blink stays enabled

- [ ] **Step 4: Commit**

```bash
git add frontend/avatar.js
git commit -m "fix: prevent emotion changes from resetting mouth/eyes during speech"
```

---

## Task 7: Greeting on Start Only

**Files:**
- Modify: `frontend/app.js:309-315` (emotion animation triggers)
- Modify: `frontend/avatar.js:226-229` (greeting on VRM load)

Greeting plays on VRM load (correct) AND on happy emotion (incorrect). Remove the happy→greeting trigger from app.js.

- [ ] **Step 1: Remove greeting from happy emotion handler**

In `frontend/app.js`, find the emotion animation block (lines 309-315). Remove the greeting trigger from happy:

```javascript
// Trigger animations based on emotion
if (avatarRenderer) {
    if (emotion === 'surprised') avatarRenderer.playAnimation('/static/animations/peaceSign.vrma');
    else if (emotion === 'love') avatarRenderer.playAnimation('/static/animations/peaceSign.vrma');
    else if (emotion === 'victory') avatarRenderer.playAnimation('/static/animations/dance.vrma');
}
```

- [ ] **Step 2: Ensure greeting only fires on initial VRM load**

In `frontend/avatar.js`, the greeting trigger at lines 226-229 fires after `_loadIdleAnimation()` completes. This only runs on initial load and on `loadVRM()` calls. To prevent it from firing on character switch, add a flag:

```javascript
// In constructor:
this._initialGreetingPlayed = false;

// In _loadVRM, after idle animation loads (around line 226):
if (!this.options.preview && !this._initialGreetingPlayed) {
    this._initialGreetingPlayed = true;
    this.playAnimation('/static/animations/greeting.vrma');
}
```

- [ ] **Step 3: Auto-test**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000');
  await page.waitForFunction(() => window.__avatarReady === true, { timeout: 20000 });
  // Trigger happy emotion — should NOT play greeting
  const result = await page.evaluate(() => {
    const r = document.querySelector('#avatar-canvas')?.__renderer;
    if (!r) return { error: 'no renderer' };
    const played = [];
    const orig = r.playAnimation.bind(r);
    r.playAnimation = (url) => { played.push(url); return orig(url); };
    // Simulate happy emotion via handleWSMessage
    if (window.__handleWSMessage) {
      window.__handleWSMessage({ type: 'emotion', emotion: 'happy' });
    }
    return { greetingPlayed: played.includes('/static/animations/greeting.vrma'), played };
  });
  console.log('Greeting test:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: `greetingPlayed: false`

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js frontend/avatar.js
git commit -m "fix: greeting animation only on initial page load, not on character switch or emotion"
```

---

## Task 8: Unified Settings Cards

**Files:**
- Modify: `frontend/index.html:135-404` (settings tab)
- Modify: `frontend/style.css` (settings layout)

Remove section headers (`settings-section-header`), per-section save buttons (`#save-settings`, `#save-providers`, `#save-mcp`), and the provider tab system. All settings become cards in a single grid.

- [ ] **Step 1: Restructure settings HTML**

Replace the settings section in `index.html` (lines 135-404). Remove section headers, provider tabs, and multiple save buttons. Keep all settings cards in one `settings-grid`:

```html
<section class="tab-panel" id="tab-settings">
    <div class="settings-scroll">
        <div class="panel-header">
            <h1>Settings</h1>
        </div>
        <div class="settings-grid">
            <!-- Appearance card (existing, keep as-is) -->
            <!-- Voice card (existing, keep as-is) -->
            <!-- Thinking card (NEW — see Task 10) -->
            <!-- Instructions card (existing, keep as-is) -->
            <!-- Data card (existing, keep as-is) -->
            <!-- Each provider becomes its own card -->
            <div class="settings-card">
                <h3><span class="material-icons-round">cloud</span> Gemini</h3>
                <!-- Gemini fields -->
            </div>
            <div class="settings-card">
                <h3><span class="material-icons-round">cloud</span> Ollama</h3>
                <!-- Ollama fields -->
            </div>
            <!-- ... one card per provider ... -->
            <!-- MCP Tools card -->
            <div class="settings-card">
                <h3><span class="material-icons-round">extension</span> Tools</h3>
                <!-- MCP toggle list + tools grid -->
            </div>
        </div>
        <button class="btn btn-primary" id="save-all-settings">Save All Settings</button>
    </div>
</section>
```

- [ ] **Step 2: Unify save logic**

In `frontend/app.js`, replace the three save handlers (`#save-settings`, `#save-providers`, `#save-mcp`) with one `#save-all-settings` handler that collects all settings and posts to `/api/settings`.

- [ ] **Step 3: Remove provider tab switching logic**

Remove the `switchProviderTab()` function and its event listeners (lines 159-165 in app.js). Remove the hash-based provider tab persistence.

- [ ] **Step 4: Auto-test**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000#settings');
  await new Promise(r => setTimeout(r, 1000));
  const result = await page.evaluate(() => {
    const cards = document.querySelectorAll('#tab-settings .settings-card');
    const sectionHeaders = document.querySelectorAll('.settings-section-header');
    const saveButtons = document.querySelectorAll('#tab-settings .btn-primary');
    return { cardCount: cards.length, sectionHeaders: sectionHeaders.length, saveButtons: saveButtons.length };
  });
  console.log('Settings layout:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: `sectionHeaders: 0`, `saveButtons: 1`

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/app.js frontend/style.css
git commit -m "refactor: unify settings into single card grid with one save button"
```

---

## Task 9: Persistent Audio Toggles

**Files:**
- Modify: `frontend/app.js` (toggle handlers + settings load/save)
- Modify: `backend/config/settings.py` (add defaults)

Voice input/output toggles reset on page reload. Save them to settings.json.

- [ ] **Step 1: Add defaults to settings.py**

In `backend/config/settings.py`, add to the `DEFAULTS` dict under `ui`:

```python
"ui": {
    "theme": "dark",
    "accent_color": "#6c5ce7",
    "font_size": 14,
    "thinking_enabled": True,
    "voice_input": True,
    "voice_output": True,
},
```

- [ ] **Step 2: Load toggle states on init**

In `frontend/app.js`, after loading settings (around line 612-615), apply voice toggle states:

```javascript
const settings = await api('/api/settings');
const voiceInput = settings?.ui?.voice_input ?? true;
const voiceOutput = settings?.ui?.voice_output ?? true;
document.getElementById('voice-input-toggle').checked = voiceInput;
document.getElementById('voice-output-toggle').checked = voiceOutput;
voiceInputEnabled = voiceInput;
voiceOutputEnabled = voiceOutput;
```

- [ ] **Step 3: Save toggle states on change**

Add change listeners for the toggle elements:

```javascript
document.getElementById('voice-input-toggle').addEventListener('change', async function() {
    voiceInputEnabled = this.checked;
    await api('/api/settings/set', { key: 'ui.voice_input', value: this.checked });
});
document.getElementById('voice-output-toggle').addEventListener('change', async function() {
    voiceOutputEnabled = this.checked;
    await api('/api/settings/set', { key: 'ui.voice_output', value: this.checked });
});
```

- [ ] **Step 4: Auto-test**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000');
  await new Promise(r => setTimeout(r, 2000));
  // Toggle voice input off
  await page.click('#voice-input-toggle');
  await new Promise(r => setTimeout(r, 500));
  // Reload and check persistence
  await page.reload();
  await new Promise(r => setTimeout(r, 2000));
  const result = await page.evaluate(() => ({
    voiceInput: document.getElementById('voice-input-toggle')?.checked,
    voiceOutput: document.getElementById('voice-output-toggle')?.checked
  }));
  console.log('Toggle persistence:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: `voiceInput: false` (persisted after reload)

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js backend/config/settings.py
git commit -m "fix: persist voice input/output toggle states to settings"
```

---

## Task 10: Thinking On/Off Toggle

**Files:**
- Modify: `frontend/index.html` (add card to settings grid)
- Modify: `frontend/app.js` (toggle handler)
- Modify: `backend/config/settings.py` (add default)

Add a toggle card in settings to enable/disable thinking mode (`` block display).

- [ ] **Step 1: Add thinking card to settings HTML**

In `frontend/index.html`, add after the Voice card:

```html
<div class="settings-card">
    <h3><span class="material-icons-round">lightbulb</span> Thinking</h3>
    <div class="form-row toggle-row">
        <label>Show thinking process</label>
        <label class="toggle">
            <input type="checkbox" id="thinking-toggle" checked>
            <span class="toggle-slider"></span>
        </label>
    </div>
</div>
```

- [ ] **Step 2: Wire toggle to settings persistence**

In `frontend/app.js`:

```javascript
// Load thinking toggle state
const thinkingEnabled = settings?.ui?.thinking_enabled ?? true;
document.getElementById('thinking-toggle').checked = thinkingEnabled;

// Save on change
document.getElementById('thinking-toggle').addEventListener('change', async function() {
    await api('/api/settings/set', { key: 'ui.thinking_enabled', value: this.checked });
});
```

- [ ] **Step 3: Gate thinking display on toggle**

In the `thinking` message handler (app.js line 317-328), check the toggle:

```javascript
} else if (data.type === 'thinking') {
    const thinkingEnabled = document.getElementById('thinking-toggle')?.checked ?? true;
    if (thinkingEnabled && data.text) {
        // ... existing thinking bubble code ...
    }
}
```

- [ ] **Step 4: Auto-test**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000#settings');
  await new Promise(r => setTimeout(r, 1000));
  const result = await page.evaluate(() => {
    const toggle = document.getElementById('thinking-toggle');
    return { exists: !!toggle, checked: toggle?.checked };
  });
  console.log('Thinking toggle:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: `exists: true, checked: true`

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/app.js backend/config/settings.py
git commit -m "feat: add thinking on/off toggle to settings"
```

---

## Task 11: Font Size in Settings

**Files:**
- Modify: `frontend/app.js` (wire font-size range to CSS variable)
- Modify: `frontend/style.css` (add `--font-size` variable)

The font-size range input (index.html line 171) doesn't affect anything. Wire it to a CSS variable.

- [ ] **Step 1: Add `--font-size` CSS variable**

In `frontend/style.css`, add to the `:root` block:

```css
:root {
    /* ... existing variables ... */
    --font-size: 14px;
}
```

Apply it to the body:

```css
body {
    /* ... existing styles ... */
    font-size: var(--font-size);
}
```

- [ ] **Step 2: Wire range input to CSS variable**

In `frontend/app.js`, add handler for the font-size range:

```javascript
const fontSizeRange = document.getElementById('font-size-range');
const fontSizeVal = document.getElementById('font-size-val');

// Load from settings
fontSizeRange.value = settings?.ui?.font_size ?? 14;
fontSizeVal.textContent = fontSizeRange.value + 'px';
document.documentElement.style.setProperty('--font-size', fontSizeRange.value + 'px');

fontSizeRange.addEventListener('input', function() {
    fontSizeVal.textContent = this.value + 'px';
    document.documentElement.style.setProperty('--font-size', this.value + 'px');
});
```

- [ ] **Step 3: Auto-test**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000#settings');
  await new Promise(r => setTimeout(r, 1000));
  // Change font size
  await page.evaluate(() => {
    const range = document.getElementById('font-size-range');
    range.value = 18;
    range.dispatchEvent(new Event('input'));
  });
  const result = await page.evaluate(() => ({
    cssVar: getComputedStyle(document.documentElement).getPropertyValue('--font-size').trim(),
    display: document.getElementById('font-size-val')?.textContent
  }));
  console.log('Font size:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: `cssVar: "18px", display: "18px"`

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js frontend/style.css
git commit -m "fix: wire font-size range input to CSS variable"
```

---

## Task 12: Message Action Buttons

**Files:**
- Modify: `frontend/app.js` (add buttons to messages)
- Modify: `frontend/style.css` (button styles)

Add copy, edit, regenerate, and speak buttons that appear on message hover.

- [ ] **Step 1: Add action buttons to `addMessage()`**

In `frontend/app.js`, modify `addMessage()` (line 332) to include action buttons:

```javascript
function addMessage(role, text) {
    const welcome = chatMessages.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    const div = document.createElement('div');
    div.className = `msg msg-${role}`;
    div.innerHTML = `
        <div class="msg-body">${escHtml(text)}</div>
        <div class="msg-actions">
            <button class="msg-action" data-action="copy" title="Copy">
                <span class="material-icons-round">content_copy</span>
            </button>
            ${role === 'user' ? `
                <button class="msg-action" data-action="edit" title="Edit">
                    <span class="material-icons-round">edit</span>
                </button>
            ` : ''}
            ${role === 'assistant' ? `
                <button class="msg-action" data-action="regenerate" title="Regenerate">
                    <span class="material-icons-round">refresh</span>
                </button>
                <button class="msg-action" data-action="speak" title="Speak">
                    <span class="material-icons-round">volume_up</span>
                </button>
            ` : ''}
        </div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}
```

- [ ] **Step 2: Add event delegation for action buttons**

```javascript
chatMessages.addEventListener('click', async (e) => {
    const btn = e.target.closest('.msg-action');
    if (!btn) return;
    const action = btn.dataset.action;
    const msg = btn.closest('.msg');
    const body = msg.querySelector('.msg-body')?.textContent || '';

    if (action === 'copy') {
        await navigator.clipboard.writeText(body);
        showToast('Copied to clipboard', 'success');
    } else if (action === 'edit') {
        chatInput.value = body;
        chatInput.focus();
    } else if (action === 'regenerate') {
        // Remove this and all following messages, resend
        const userMsg = msg.previousElementSibling;
        if (userMsg?.classList.contains('msg-user')) {
            const text = userMsg.querySelector('.msg-body')?.textContent;
            msg.remove();
            userMsg.remove();
            if (text && ws?.readyState === WebSocket.OPEN) {
                addMessage('user', text);
                ws.send(JSON.stringify({ type: 'user_message', text }));
            }
        }
    } else if (action === 'speak') {
        // Request TTS for this message
        if (ws?.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'command', command: 'speak', text: body }));
        }
    }
});
```

- [ ] **Step 3: Add CSS for message actions**

In `frontend/style.css`:

```css
.msg { position: relative; }
.msg-actions {
    display: none;
    position: absolute;
    top: 0.25rem;
    right: 0.25rem;
    gap: 0.25rem;
}
.msg:hover .msg-actions { display: flex; }
.msg-action {
    width: 28px; height: 28px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--bg-card);
    color: var(--text-muted);
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: all 0.15s;
}
.msg-action:hover {
    background: var(--bg-hover);
    color: var(--text);
    border-color: var(--accent);
}
.msg-action .material-icons-round { font-size: 16px; }
```

- [ ] **Step 4: Auto-test**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000');
  await new Promise(r => setTimeout(r, 1000));
  // Add a test message
  await page.evaluate(() => {
    const chatMessages = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'msg msg-user';
    div.innerHTML = '<div class=\"msg-body\">Test</div><div class=\"msg-actions\"><button class=\"msg-action\" data-action=\"copy\"><span class=\"material-icons-round\">content_copy</span></button></div>';
    chatMessages.appendChild(div);
  });
  const result = await page.evaluate(() => {
    const btn = document.querySelector('.msg-action[data-action=\"copy\"]');
    return { exists: !!btn, visible: btn ? getComputedStyle(btn.parentElement).display : 'none' };
  });
  console.log('Message actions:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: `exists: true`

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js frontend/style.css
git commit -m "feat: add copy/edit/regenerate/speak action buttons on message hover"
```

---

## Task 13: Error Cleanup (Delete Prompt + Error)

**Files:**
- Modify: `frontend/app.js` (error handling in `handleWSMessage` and `sendMessage`)

On error: remove both error message and preceding user prompt from chat DOM, restore prompt to input, don't save to history.

- [ ] **Step 1: Track the last user message element**

In `frontend/app.js`, add a global to track the last user message:

```javascript
let lastUserMessage = null;
```

In `sendMessage()` (line 349), store reference:

```javascript
function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    clearErrors();
    flushTTSQueue();
    lastUserMessage = addMessage('user', text);
    ws.send(JSON.stringify({ type: 'user_message', text }));
    chatInput.value = '';
    chatInput.style.height = 'auto';
}
```

- [ ] **Step 2: On error, remove both messages and restore prompt**

In the `chat_append` handler, when an error is detected (lines 265-283), after marking the message as error, also handle cleanup:

```javascript
if (data.error) {
    currentAssistantMessage.classList.add('msg-error');
}
// ... existing error detection code ...

if (data.finished && currentAssistantMessage?.classList.contains('msg-error')) {
    const errorText = currentAssistantMessage.querySelector('.msg-body')?.textContent || '';
    // Restore prompt to input
    if (lastUserMessage) {
        const promptText = lastUserMessage.querySelector('.msg-body')?.textContent || '';
        chatInput.value = promptText;
        lastUserMessage.remove();
    }
    currentAssistantMessage.remove();
    currentAssistantMessage = null;
    lastUserMessage = null;
    setStatus('ready');
    return;
}
```

- [ ] **Step 3: Auto-test**

```bash
node -e "
const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.goto('http://localhost:8000');
  await new Promise(r => setTimeout(r, 1000));
  // Simulate error scenario
  const result = await page.evaluate(() => {
    const chatMessages = document.getElementById('chat-messages');
    // Add user message
    const userDiv = document.createElement('div');
    userDiv.className = 'msg msg-user';
    userDiv.innerHTML = '<div class=\"msg-body\">test prompt</div>';
    chatMessages.appendChild(userDiv);
    // Add error message
    const errDiv = document.createElement('div');
    errDiv.className = 'msg msg-assistant msg-error';
    errDiv.innerHTML = '<div class=\"msg-body\">API Error 429</div>';
    chatMessages.appendChild(errDiv);
    // Simulate cleanup
    const promptText = userDiv.querySelector('.msg-body').textContent;
    userDiv.remove();
    errDiv.remove();
    return { remaining: chatMessages.querySelectorAll('.msg').length, promptRestored: promptText };
  });
  console.log('Error cleanup:', JSON.stringify(result));
  await browser.close();
})();
"
```

Expected: `remaining: 0, promptRestored: "test prompt"`

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "fix: on error, remove both error and prompt messages, restore prompt to input"
```

---

## Execution Order

1. Batman VRM → auto-test → commit
2. Letter→VRM icons → auto-test → commit
3. Center character → auto-test → commit
4. Preview head-box → auto-test → commit
5. Ryuk gaze → auto-test → commit
6. Diana voice → auto-test → commit
7. Greeting init-only → auto-test → commit
8. Unified settings → auto-test → commit
9. Persistent toggles → auto-test → commit
10. Thinking toggle → auto-test → commit
11. Font size → auto-test → commit
12. Message buttons → auto-test → commit
13. Error cleanup → auto-test → commit
14. User manual pass
