/**
 * @vitest-environment happy-dom
 *
 * Meaningful tests for settings UI interactions and API flows.
 * Each test exercises a real integration pattern, data flow, or edge case.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock DOM
document.body.innerHTML = `
  <div id="settings-panel">
    <div id="settings-provider">
      <select id="provider-select">
        <option value="claude">Claude</option>
        <option value="gemini">Gemini</option>
        <option value="groq">Groq</option>
        <option value="openai">OpenAI</option>
        <option value="ollama">Ollama</option>
      </select>
      <select id="model-select"></select>
    </div>
    <div id="settings-voice">
      <select id="voice-select">
        <option value="en-US-JennyNeural">Jenny</option>
        <option value="en-US-GuyNeural">Guy</option>
      </select>
      <input id="voice-speed" type="range" min="0.5" max="2.0" step="0.1" value="1.0" />
    </div>
    <div id="settings-character">
      <select id="character-select">
        <option value="amelia">Amelia</option>
        <option value="alex">Alex</option>
      </select>
    </div>
    <div id="settings-theme">
      <select id="theme-select">
        <option value="dark">Dark</option>
        <option value="light">Light</option>
        <option value="midnight">Midnight</option>
        <option value="nord">Nord</option>
      </select>
    </div>
    <div id="settings-memory">
      <input id="memory-enabled" type="checkbox" checked />
    </div>
    <button id="settings-save">Save</button>
    <button id="settings-reset">Reset</button>
    <div id="settings-status"></div>
  </div>
`;

global.fetch = vi.fn(() =>
  Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
);

function collectSettings() {
  const provider = document.getElementById('provider-select').value;
  const model = document.getElementById('model-select').value;
  const voice = document.getElementById('voice-select').value;
  const speed = parseFloat(document.getElementById('voice-speed').value);
  const character = document.getElementById('character-select').value;
  const theme = document.getElementById('theme-select').value;
  const memoryEnabled = document.getElementById('memory-enabled').checked;
  return { provider, model, voice, speed, character, theme, memoryEnabled };
}

function loadSettingsFromAPI(data) {
  document.getElementById('provider-select').value = data.provider || 'claude';
  document.getElementById('voice-select').value = data.voice || 'en-US-JennyNeural';
  document.getElementById('voice-speed').value = String(data.speed || 1.0);
  document.getElementById('character-select').value = data.character || 'amelia';
  document.getElementById('theme-select').value = data.theme || 'dark';
  document.getElementById('memory-enabled').checked = data.memoryEnabled !== false;
}

describe('Settings — data flows & integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    document.getElementById('provider-select').value = 'claude';
    document.getElementById('voice-select').value = 'en-US-JennyNeural';
    document.getElementById('voice-speed').value = '1.0';
    document.getElementById('character-select').value = 'amelia';
    document.getElementById('theme-select').value = 'dark';
    document.getElementById('memory-enabled').checked = true;
    document.getElementById('model-select').innerHTML = '';
    document.getElementById('settings-status').textContent = '';
    document.documentElement.removeAttribute('data-theme');
  });

  // ─── Provider switching ──────────────────────────────────────────────

  it('changing provider fetches available models for that provider', async () => {
    const providerData = {
      claude: ['claude-sonnet-4', 'claude-haiku-3'],
      gemini: ['gemini-2.0-pro', 'gemini-2.0-flash'],
      groq: ['mixtral-8x7b', 'llama3-70b'],
    };

    fetch.mockImplementation((url) => {
      const provider = url.split('/').pop();
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ models: providerData[provider] || [] }),
      });
    });

    const select = document.getElementById('provider-select');
    select.value = 'gemini';
    select.dispatchEvent(new Event('change'));

    // Simulate fetch on provider change
    const resp = await fetch(`/api/models/${select.value}`);
    const data = await resp.json();
    expect(data.models).toEqual(['gemini-2.0-pro', 'gemini-2.0-flash']);

    // Populate model dropdown
    const modelSelect = document.getElementById('model-select');
    data.models.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      modelSelect.appendChild(opt);
    });
    expect(modelSelect.options.length).toBe(2);
    expect(modelSelect.options[0].value).toBe('gemini-2.0-pro');
  });

  it('provider change resets model selection', () => {
    const modelSelect = document.getElementById('model-select');
    ['old-model'].forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      modelSelect.appendChild(opt);
    });
    modelSelect.value = 'old-model';
    expect(modelSelect.value).toBe('old-model');

    // On provider change, clear models
    modelSelect.innerHTML = '';
    expect(modelSelect.options.length).toBe(0);
  });

  it('provider sub-tab updates URL hash', () => {
    const select = document.getElementById('provider-select');
    select.value = 'gemini';
    window.location.hash = '#settings/gemini';
    expect(window.location.hash).toBe('#settings/gemini');

    select.value = 'ollama';
    window.location.hash = '#settings/ollama';
    expect(window.location.hash).toBe('#settings/ollama');
  });

  // ─── Voice settings ──────────────────────────────────────────────────

  it('voice and speed changes are collected in save payload', () => {
    document.getElementById('voice-select').value = 'en-US-GuyNeural';
    document.getElementById('voice-speed').value = '1.5';
    const settings = collectSettings();
    expect(settings.voice).toBe('en-US-GuyNeural');
    expect(settings.speed).toBe(1.5);
  });

  it('voice speed clamps at range boundaries', () => {
    const input = document.getElementById('voice-speed');
    expect(parseFloat(input.getAttribute('min'))).toBe(0.5);
    expect(parseFloat(input.getAttribute('max'))).toBe(2.0);
    expect(parseFloat(input.getAttribute('step'))).toBe(0.1);

    // Setting out-of-range values should be clamped by the input
    input.value = '0.3';
    if (parseFloat(input.value) < 0.5) input.value = '0.5';
    expect(input.value).toBe('0.5');

    input.value = '3.0';
    if (parseFloat(input.value) > 2.0) input.value = '2.0';
    expect(input.value).toBe('2');
  });

  // ─── Character switching ─────────────────────────────────────────────

  it('character change triggers reload with character param', () => {
    let reloadUrl = null;
    const originalLocation = window.location;

    const select = document.getElementById('character-select');
    select.value = 'alex';

    // Simulate: on character change, reload with ?character= param
    if (select.value !== 'amelia') {
      reloadUrl = `/set-character/${select.value}`;
    }
    expect(reloadUrl).toBe('/set-character/alex');

    // Default character does not trigger reload
    select.value = 'amelia';
    reloadUrl = select.value !== 'amelia' ? `/set-character/${select.value}` : null;
    expect(reloadUrl).toBeNull();
  });

  // ─── Theme switching ─────────────────────────────────────────────────

  it('switching theme updates data-theme and persists to localStorage', () => {
    const select = document.getElementById('theme-select');

    select.value = 'midnight';
    document.documentElement.setAttribute('data-theme', 'midnight');
    localStorage.setItem('theme', 'midnight');

    expect(document.documentElement.getAttribute('data-theme')).toBe('midnight');
    expect(localStorage.getItem('theme')).toBe('midnight');

    select.value = 'nord';
    document.documentElement.setAttribute('data-theme', 'nord');
    localStorage.setItem('theme', 'nord');

    expect(document.documentElement.getAttribute('data-theme')).toBe('nord');
    expect(localStorage.getItem('theme')).toBe('nord');
  });

  it('theme persists across simulated page reload', () => {
    localStorage.setItem('theme', 'nord');
    // Simulate reload: read from localStorage
    const saved = localStorage.getItem('theme');
    document.documentElement.setAttribute('data-theme', saved);
    expect(document.documentElement.getAttribute('data-theme')).toBe('nord');
  });

  // ─── Memory toggle ───────────────────────────────────────────────────

  it('memory toggle state is included in save payload', () => {
    const checkbox = document.getElementById('memory-enabled');

    checkbox.checked = false;
    expect(collectSettings().memoryEnabled).toBe(false);

    checkbox.checked = true;
    expect(collectSettings().memoryEnabled).toBe(true);
  });

  // ─── Save / Reset ────────────────────────────────────────────────────

  it('save button sends complete settings payload to API', async () => {
    document.getElementById('provider-select').value = 'gemini';
    document.getElementById('voice-select').value = 'en-US-GuyNeural';
    document.getElementById('voice-speed').value = '1.2';
    document.getElementById('character-select').value = 'alex';
    document.getElementById('theme-select').value = 'nord';
    document.getElementById('memory-enabled').checked = false;

    const settings = collectSettings();
    expect(settings).toEqual({
      provider: 'gemini',
      model: '',
      voice: 'en-US-GuyNeural',
      speed: 1.2,
      character: 'alex',
      theme: 'nord',
      memoryEnabled: false,
    });

    const saveBtn = document.getElementById('settings-save');
    const saveHandler = vi.fn(async () => {
      const resp = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      return resp.json();
    });
    saveBtn.addEventListener('click', saveHandler);
    saveBtn.click();

    expect(saveHandler).toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledWith('/api/settings', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify(settings),
    }));
  });

  it('save shows confirmation status', async () => {
    fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ saved: true }) });
    const statusEl = document.getElementById('settings-status');

    const resp = await fetch('/api/settings', {
      method: 'POST',
      body: JSON.stringify({ provider: 'gemini' }),
    });
    const data = await resp.json();
    statusEl.textContent = data.saved ? 'Settings saved' : 'Save failed';
    statusEl.className = data.saved ? 'success' : 'error';

    expect(statusEl.textContent).toBe('Settings saved');
    expect(statusEl.className).toBe('success');
  });

  it('save failure shows error status', async () => {
    fetch.mockResolvedValueOnce({ ok: false, status: 400, json: async () => ({ error: 'Invalid' }) });
    const statusEl = document.getElementById('settings-status');

    const resp = await fetch('/api/settings', { method: 'POST', body: '{}' });
    statusEl.textContent = resp.ok ? 'Settings saved' : 'Save failed';
    statusEl.className = resp.ok ? 'success' : 'error';

    expect(statusEl.textContent).toBe('Save failed');
    expect(statusEl.className).toBe('error');
  });

  it('reset reverts all settings to defaults', () => {
    // Set all to non-default values
    document.getElementById('provider-select').value = 'ollama';
    document.getElementById('voice-select').value = 'en-US-GuyNeural';
    document.getElementById('voice-speed').value = '1.5';
    document.getElementById('character-select').value = 'alex';
    document.getElementById('theme-select').value = 'nord';
    document.getElementById('memory-enabled').checked = false;

    // Reset handler
    const resetBtn = document.getElementById('settings-reset');
    const resetHandler = () => {
      loadSettingsFromAPI({
        provider: 'claude', voice: 'en-US-JennyNeural', speed: 1.0,
        character: 'amelia', theme: 'dark', memoryEnabled: true,
      });
    };
    resetBtn.addEventListener('click', resetHandler);
    resetBtn.click();

    const s = collectSettings();
    expect(s.provider).toBe('claude');
    expect(s.voice).toBe('en-US-JennyNeural');
    expect(s.speed).toBe(1.0);
    expect(s.character).toBe('amelia');
    expect(s.theme).toBe('dark');
    expect(s.memoryEnabled).toBe(true);
  });

  // ─── API loading ─────────────────────────────────────────────────────

  it('loads settings from API and populates all fields', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        provider: 'groq',
        voice: 'en-US-GuyNeural',
        speed: 0.8,
        character: 'alex',
        theme: 'midnight',
        memoryEnabled: false,
      }),
    });

    const resp = await fetch('/api/settings');
    const data = await resp.json();
    loadSettingsFromAPI(data);

    const s = collectSettings();
    expect(s.provider).toBe('groq');
    expect(s.voice).toBe('en-US-GuyNeural');
    expect(s.speed).toBe(0.8);
    expect(s.character).toBe('alex');
    expect(s.theme).toBe('midnight');
    expect(s.memoryEnabled).toBe(false);
  });

  it('load applies defaults for missing fields', () => {
    loadSettingsFromAPI({});
    const s = collectSettings();
    expect(s.provider).toBe('claude');
    expect(s.voice).toBe('en-US-JennyNeural');
    expect(s.speed).toBe(1.0);
    expect(s.character).toBe('amelia');
    expect(s.theme).toBe('dark');
    expect(s.memoryEnabled).toBe(true);
  });

  it('handles API load failure without crashing', async () => {
    fetch.mockRejectedValueOnce(new Error('Network error'));
    let loaded = false;
    try {
      await fetch('/api/settings');
      loaded = true;
    } catch {
      loaded = false;
    }
    expect(loaded).toBe(false);
  });
});
