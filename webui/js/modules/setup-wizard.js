/**
 * setup-wizard.js — First-run setup wizard
 */
import { BASE_URL } from './config.js';
import { escHtml, trapFocus } from './utils.js';
import { setSettingsCache } from './state.js';

let _setupMode = null;
let _setupProviders = [];
let _selectedProvider = null;
let _setupCurrentStep = 1;

// ─── Dynamic options cache ────────────────────────────────────────────

async function _populateSelect(selectId, url, valueAttr, labelAttr) {
    const select = document.getElementById(selectId);
    if (!select) return;
    try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        const items = Array.isArray(data) ? data : (data.options || data.items || []);
        select.innerHTML = '';
        // Support both [{value, label}] and [string] array shapes
        const hasCustom = valueAttr || labelAttr;
        items.forEach(item => {
            const opt = document.createElement('option');
            if (hasCustom) {
                opt.value = item[valueAttr] || item;
                opt.textContent = item[labelAttr] || item;
            } else if (typeof item === 'string') {
                opt.value = item;
                opt.textContent = item;
            } else {
                opt.value = item.value || item.id || '';
                opt.textContent = item.label || item.name || opt.value;
            }
            select.appendChild(opt);
        });
    } catch (e) {
        console.warn(`Failed to populate ${selectId}:`, e);
    }
}

export async function populateSetupOptions() {
    await Promise.all([
        _populateSelect('setup-stt', `${BASE_URL}/api/settings/options/stt_engines`),
        _populateSelect('setup-tts', `${BASE_URL}/api/settings/options/tts_engines`),
        _populateSelect('setup-character', `${BASE_URL}/api/characters`, 'id', 'name'),
        _populateSelect('setup-permission', `${BASE_URL}/api/settings/options/permission_levels`),
    ]);
}

export async function showSetupWizard() {
    const wizard = document.getElementById('setup-wizard-overlay');
    if (wizard) {
        wizard.style.display = 'flex';
        _showSetupStep('welcome');
        _setupMode = null;
        _selectedProvider = null;
        _setupCurrentStep = 1;
        trapFocus(wizard);
    }
}

function hideSetupWizard() {
    const wizard = document.getElementById('setup-wizard-overlay');
    if (wizard) {
        wizard.style.display = 'none';
        if (wizard._trapFocusHandler) {
            wizard.removeEventListener('keydown', wizard._trapFocusHandler);
            delete wizard._trapFocusHandler;
        }
    }
}

function _showSetupStep(step) {
    document.querySelectorAll('.setup-step').forEach(s => s.style.display = 'none');
    const el = document.getElementById('setup-' + step);
    if (el) {
        el.style.display = 'flex';
        const first = el.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        setTimeout(() => first?.focus(), 100);
    }
}

export function _initSetupWizard() {
    document.getElementById('setup-mode-minimal')?.addEventListener('click', () => _selectSetupMode('minimal'));
    document.getElementById('setup-mode-minimal')?.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _selectSetupMode('minimal'); } });
    document.getElementById('setup-mode-advanced')?.addEventListener('click', () => _selectSetupMode('advanced'));
    document.getElementById('setup-mode-advanced')?.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _selectSetupMode('advanced'); } });

    document.getElementById('setup-back-step1')?.addEventListener('click', () => _showSetupStep('welcome'));
    document.getElementById('setup-back-step2')?.addEventListener('click', () => _showSetupStep('step1'));
    document.getElementById('setup-back-step3')?.addEventListener('click', () => _showSetupStep('step2'));

    document.getElementById('setup-provider-grid')?.addEventListener('click', e => {
        const option = e.target.closest('.setup-provider-option');
        if (option) {
            const pid = option.dataset.providerId;
            if (pid) _selectSetupProvider(pid);
        }
    });

    document.getElementById('setup-test-btn')?.addEventListener('click', testSetupConnection);
    document.getElementById('setup-continue-btn')?.addEventListener('click', () => _advanceFromStep1());
    document.getElementById('setup-voice-continue-btn')?.addEventListener('click', () => _showSetupStep('step3'));
    document.getElementById('setup-save-btn')?.addEventListener('click', saveSetupWizard);

    // Populate dynamic selects from backend APIs
    populateSetupOptions();
}

function _selectSetupMode(mode) {
    _setupMode = mode;
    document.querySelectorAll('.setup-mode-card').forEach(c => c.classList.remove('selected'));
    document.getElementById('setup-mode-' + mode)?.classList.add('selected');

    const totalSteps = mode === 'minimal' ? '1' : '3';
    document.getElementById('setup-total-steps').textContent = totalSteps;
    document.getElementById('setup-total-steps2').textContent = totalSteps;
    document.getElementById('setup-total-steps3').textContent = totalSteps;
    document.getElementById('setup-step1-title').textContent = 'Choose Your Provider';

    _loadProviders().then(() => {
        _setupCurrentStep = 1;
        _showSetupStep('step1');
    });
}

async function _loadProviders() {
    const loadingEl = document.getElementById('setup-providers-loading');
    const listEl = document.getElementById('setup-providers-list');
    const grid = document.getElementById('setup-provider-grid');

    loadingEl.style.display = 'flex';
    listEl.style.display = 'none';

    try {
        const resp = await fetch(`${BASE_URL}/api/providers`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        _setupProviders = data.providers || [];

        grid.innerHTML = _setupProviders.map(p => {
            let badges = '';
            if (p.has_free_tier) badges += '<span class="provider-badge">Free</span>';
            if (p.has_api_key) badges += '<span class="provider-badge configured">Configured</span>';
            return `
            <div class="setup-provider-option" data-provider-id="${p.id}" role="button" tabindex="0">
                <span>${escHtml(p.name)}</span>
                ${badges}
            </div>`;
        }).join('');

        loadingEl.style.display = 'none';
        listEl.style.display = 'block';
    } catch (e) {
        loadingEl.innerHTML = `<span class="material-icons-round" style="color:var(--danger)">error</span><span>Failed to load providers: ${escHtml(e.message || String(e))}</span>`;
    }
}

function _selectSetupProvider(pid) {
    _selectedProvider = pid;
    document.querySelectorAll('.setup-provider-option').forEach(el => {
        el.classList.toggle('selected', el.dataset.providerId === pid);
    });

    const provider = _setupProviders.find(p => p.id === pid);
    if (!provider) return;

    const detailEl = document.getElementById('setup-provider-detail');
    const apiKeyInput = document.getElementById('setup-api-key');
    const apiKeyDesc = document.getElementById('setup-api-key-desc');
    const modelSelect = document.getElementById('setup-model');
    const baseUrlGroup = document.getElementById('setup-base-url-group');
    const baseUrlInput = document.getElementById('setup-base-url');
    const baseUrlDesc = document.getElementById('setup-base-url-desc');

    if (provider.needs_api_key) {
        apiKeyInput.style.display = '';
        apiKeyInput.required = true;
        apiKeyDesc.textContent = provider.api_key_hint || 'Your key stays on this device.';
    } else {
        apiKeyInput.style.display = 'none';
        apiKeyInput.required = false;
        apiKeyDesc.textContent = 'No API key needed for local providers.';
    }

    // Show/hide base_url based on whether it's constant
    if (provider.base_url_constant) {
        // Constant URL — show as disabled with pre-filled value
        baseUrlGroup.style.display = '';
        baseUrlInput.value = provider.base_url || '';
        baseUrlInput.disabled = true;
        baseUrlInput.readOnly = true;
        baseUrlDesc.textContent = 'Fixed endpoint — provided automatically.';
    } else if (provider.base_url !== undefined) {
        // Editable URL — show as empty, editable input
        baseUrlGroup.style.display = '';
        baseUrlInput.value = provider.base_url || '';
        baseUrlInput.disabled = false;
        baseUrlInput.readOnly = false;
        baseUrlInput.placeholder = 'https://api.example.com/v1';
        baseUrlDesc.textContent = 'Override the default API endpoint URL.';
    } else {
        // No base_url info — hide the field
        baseUrlGroup.style.display = 'none';
    }

    modelSelect.innerHTML = '';
    if (provider.models && provider.models.length > 0) {
        provider.models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m; opt.textContent = m;
            modelSelect.appendChild(opt);
        });
        if (provider.default_model) modelSelect.value = provider.default_model;
    } else {
        const opt = document.createElement('option');
        opt.value = ''; opt.textContent = 'No preset models (type manually)';
        modelSelect.appendChild(opt);
    }

    detailEl.style.display = 'block';
    _updateContinueButton();
    if (provider.needs_api_key) setTimeout(() => apiKeyInput?.focus(), 150);
}

function _updateContinueButton() {
    const provider = _setupProviders.find(p => p.id === _selectedProvider);
    const apiKeyInput = document.getElementById('setup-api-key');
    const continueBtn = document.getElementById('setup-continue-btn');
    if (!provider) { continueBtn.disabled = true; return; }
    if (provider.needs_api_key) {
        const key = apiKeyInput?.value?.trim() || '';
        continueBtn.disabled = !key;
    } else {
        continueBtn.disabled = false;
    }
}

function _advanceFromStep1() {
    if (_setupMode === 'minimal') { saveSetupWizard(); return; }
    _showSetupStep('step2');
}

async function testSetupConnection() {
    const provider = _selectedProvider;
    const apiKey = document.getElementById('setup-api-key').value.trim();
    const baseUrl = document.getElementById('setup-base-url')?.value?.trim() || '';
    const testBtn = document.getElementById('setup-test-btn');
    const testResult = document.getElementById('setup-test-result');

    if (!provider) {
        testResult.style.color = 'var(--danger, #ef4444)';
        testResult.textContent = 'Please select a provider first';
        testResult.style.display = 'block';
        return;
    }

    testBtn.disabled = true;
    testBtn.textContent = 'Testing...';
    testResult.style.display = 'none';

    try {
        // Save API key and base_url before testing
        await fetch(`${BASE_URL}/api/settings/set`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: `provider.${provider}.api_key`, value: apiKey })
        });
        if (baseUrl) {
            await fetch(`${BASE_URL}/api/settings/set`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: `provider.${provider}.base_url`, value: baseUrl })
            });
        }
        const resp = await fetch(`${BASE_URL}/api/settings/test/${provider}`, { method: 'POST' });
        const data = await resp.json();

        if (data.ok) {
            testResult.style.color = 'var(--success, #22c55e)';
            testResult.textContent = `✓ Connected (${data.latency_ms || '?'}ms)`;
        } else {
            testResult.style.color = 'var(--danger, #ef4444)';
            testResult.textContent = `✗ ${data.error || 'Connection failed'}`;
        }
        testResult.style.display = 'block';
    } catch (e) {
        testResult.style.color = 'var(--danger, #ef4444)';
        testResult.textContent = `✗ Error: ${e.message}`;
        testResult.style.display = 'block';
    } finally {
        testBtn.disabled = false;
        testBtn.textContent = 'Test Connection';
    }
}

async function saveSetupWizard() {
    const provider = _selectedProvider;
    const apiKeyInput = document.getElementById('setup-api-key');
    const apiKey = apiKeyInput?.value?.trim() || '';
    const modelSelect = document.getElementById('setup-model');
    const model = modelSelect?.value?.trim() || '';
    const baseUrlInput = document.getElementById('setup-base-url');
    const baseUrl = baseUrlInput?.value?.trim() || '';
    const errorEl = document.getElementById('setup-error');

    if (!provider) {
        errorEl.textContent = 'Please select a provider.';
        errorEl.style.display = 'block';
        return;
    }

    const provObj = _setupProviders.find(p => p.id === provider);
    if (provObj?.needs_api_key && !apiKey) {
        errorEl.textContent = 'Please enter an API key.';
        errorEl.style.display = 'block';
        return;
    }

    const saveBtn = document.getElementById('setup-save-btn') || document.getElementById('setup-continue-btn');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving...'; }
    errorEl.style.display = 'none';

    try {
        const resp = await fetch(`${BASE_URL}/api/setup/step1`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, api_key: apiKey, model, base_url: baseUrl }),
        });
        const data = await resp.json();
        if (data.ok || !provObj?.needs_api_key) {
            if (_setupMode === 'advanced') {
                // Ensure WebUI mode and WebUI STT engine are set
                await fetch(`${BASE_URL}/api/settings/set`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: 'ui.mode', value: 'webui' })
                });
                await fetch(`${BASE_URL}/api/settings/set`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: 'voice.stt_engine_webui', value: document.getElementById('setup-stt')?.value || 'browser' })
                });
                await fetch(`${BASE_URL}/api/setup/step2`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        stt_engine: document.getElementById('setup-stt')?.value || 'browser',
                        tts_engine: document.getElementById('setup-tts')?.value || 'edge-tts',
                        voice_input_enabled: document.getElementById('setup-voice-input')?.checked ?? true,
                        voice_output_enabled: document.getElementById('setup-voice-output')?.checked ?? true,
                    })
                });
                await fetch(`${BASE_URL}/api/setup/step3`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        character: document.getElementById('setup-character')?.value || 'default',
                        permission_level: document.getElementById('setup-permission')?.value || 'confirm',
                        companion_enabled: document.getElementById('setup-companion')?.checked ?? false,
                        thinking_enabled: document.getElementById('setup-thinking')?.checked ?? true,
                    })
                });
            } else {
                await fetch(`${BASE_URL}/api/settings/set`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: 'ui.mode', value: 'webui' })
                });
                await fetch(`${BASE_URL}/api/setup/step2`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
                await fetch(`${BASE_URL}/api/setup/step3`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
            }

            _showSetupStep('wizard-done');
            setTimeout(hideSetupWizard, 2000);

            fetch(`${BASE_URL}/api/settings`).then(r => r.json()).then(s => {
                setSettingsCache(s);
            }).catch(() => {});
        } else {
            if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save & Start Chatting'; }
            errorEl.textContent = data.error || data.detail || 'Connection failed. Check your API key and try again.';
            errorEl.style.display = 'block';
        }
    } catch (e) {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save & Start Chatting'; }
        errorEl.textContent = `Error: ${e.message}`;
        errorEl.style.display = 'block';
    }
}
