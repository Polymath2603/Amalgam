/**
 * settings.js — Settings panel rendering and management
 */
import { BASE_URL } from './config.js';
import { escHtml, _getNestedValue, showToast, applyTheme, applyAccentColor } from './utils.js';
import { api } from './api-client.js';
import { PROVIDER_DISPLAY_NAMES, PROVIDER_MODELS, SETTINGS_SCHEMA, initProviderData } from './settings-schema.js';
import { getSettings, setSettingsCache } from './state.js';
import { t } from '../i18n.js';

let activeSettingsTab = 'Character';
let _providerList = null;
let _charList = null;
let _vaultFiles = [];
let _currentVaultFile = null;

export function getActiveSettingsTab() { return activeSettingsTab; }
export function setActiveSettingsTab(v) { activeSettingsTab = v; }

// Internal helpers
function _getFieldKey(fieldId, field) {
    const settings = getSettings() || {};
    if (field.key_dynamic) {
        const active = _getNestedValue(settings, 'provider.active') || 'gemini';
        const suffix = field.key_suffix || fieldId;
        return `provider.${active}.${suffix}`;
    }
    return field.key || fieldId;
}

function _getFieldValue(fieldId, field) {
    const settings = getSettings() || {};
    const key = _getFieldKey(fieldId, field);
    let val = _getNestedValue(settings, key);
    if ((val === undefined || val === null) && field.key_dynamic && field.key_suffix) {
        const active = _getNestedValue(settings, 'provider.active') || 'gemini';
        const altKey = `provider.${active}.${fieldId}`;
        val = _getNestedValue(settings, altKey);
    }
    return val ?? '';
}

function _getFieldOptions(fieldId, field) {
    if (field.dynamic_options) {
        const settings = getSettings() || {};
        const active = _getNestedValue(settings, 'provider.active') || 'gemini';
        return PROVIDER_MODELS[active] || [];
    }
    if (field.dynamic_providers) {
        return _providerList || [];
    }
    if (field.dynamic_characters) {
        return _charList || [];
    }
    return field.options || [];
}

function _shouldShowField(fieldId, field) {
    if (!field.show_if) return true;
    const settings = getSettings() || {};
    const sf = field.show_if;
    let currentVal;
    if (sf.field === 'active_provider') {
        const domEl = document.getElementById('field-active_provider');
        currentVal = domEl ? domEl.value : (_getNestedValue(settings, 'provider.active') || 'gemini');
    } else if (sf.field === 'stt_engine') {
        const domEl = document.getElementById('field-stt_engine');
        currentVal = domEl ? domEl.value : (_getNestedValue(settings, 'voice.stt_engine') || 'browser');
    } else if (sf.field === 'tts_engine') {
        const domEl = document.getElementById('field-tts_engine');
        currentVal = domEl ? domEl.value : (_getNestedValue(settings, 'voice.engine') || 'edge-tts');
    } else {
        for (const cat of Object.values(SETTINGS_SCHEMA)) {
            if (cat.fields[sf.field]) {
                const domEl = document.getElementById(`field-${sf.field}`);
                currentVal = domEl ? domEl.value : _getFieldValue(sf.field, cat.fields[sf.field]);
                break;
            }
        }
    }
    if (sf.equals) return String(currentVal) === sf.equals;
    if (sf.not_in) return !sf.not_in.includes(String(currentVal));
    return true;
}

export function renderField(fieldId, field) {
    const settings = getSettings() || {};
    const key = _getFieldKey(fieldId, field);
    let value = _getFieldValue(fieldId, field);
    const options = _getFieldOptions(fieldId, field);
    const desc = field.description ? `<span class="field-desc">${escHtml(field.description)}</span>` : '';
    const commonAttrs = `id="field-${fieldId}" data-key="${escHtml(key)}" data-field="${fieldId}"`;

    switch (field.type) {
        case 'toggle': {
            const checked = value === true || value === 'true' ? 'checked' : '';
            return `
                <div class="settings-field" data-field="${fieldId}">
                    <div class="field-label-row">
                        <label for="field-${fieldId}">${field.label}</label>
                        <label class="toggle-switch">
                            <input type="checkbox" ${commonAttrs} ${checked}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    ${desc}
                </div>
            `;
        }
        case 'select': {
            const opts = options.map(opt => {
                const val = typeof opt === 'object' ? opt.value : opt;
                const label = typeof opt === 'object' ? opt.label : (PROVIDER_DISPLAY_NAMES[opt] || opt);
                return `<option value="${escHtml(val)}" ${String(value) === val ? 'selected' : ''}>${escHtml(label)}</option>`;
            }).join('');
            let actionBtn = '';
            if (field.dynamic_options) {
                const active = _getNestedValue(settings, 'provider.active') || 'gemini';
                actionBtn = `<button class="icon-btn fetch-models-btn" data-provider="${escHtml(active)}" title="Fetch models from provider">
                    <span class="material-icons-round">cloud_sync</span>
                </button>`;
            }
            if (fieldId === 'tts_engine') {
                actionBtn += `<button class="icon-btn test-voice-btn" title="Test Voice">
                    <span class="material-icons-round">volume_up</span>
                </button>`;
            }
            return `
                <div class="settings-field" data-field="${fieldId}">
                    <label for="field-${fieldId}">${field.label}</label>
                    <div class="input-with-action">
                        <select ${commonAttrs}>${opts}</select>
                        ${actionBtn}
                    </div>
                    ${desc}
                </div>
            `;
        }
        case 'password': {
            return `
                <div class="settings-field" data-field="${fieldId}">
                    <label for="field-${fieldId}">${field.label}</label>
                    <div class="input-with-action">
                        <input type="password" ${commonAttrs} value="${escHtml(String(value))}" placeholder="${field.label}">
                        <button class="icon-btn toggle-vis-btn" data-toggle-vis="${fieldId}" title="Show/hide">
                            <span class="material-icons-round">visibility</span>
                        </button>
                        <button class="icon-btn test-conn-btn" title="Test connection">
                            <span class="material-icons-round">wifi_find</span>
                        </button>
                    </div>
                    ${desc}
                </div>
            `;
        }
        case 'number': {
            return `
                <div class="settings-field" data-field="${fieldId}">
                    <label for="field-${fieldId}">${field.label}</label>
                    <input type="number" ${commonAttrs} value="${escHtml(String(value))}" min="${field.min || 0}" max="${field.max || 999}" step="${field.step || 1}">
                    ${desc}
                </div>
            `;
        }
        case 'range': {
            const val = value || field.min || 0;
            return `
                <div class="settings-field" data-field="${fieldId}">
                    <label for="field-${fieldId}">${field.label}</label>
                    <div class="range-row">
                        <input type="range" ${commonAttrs} value="${val}" min="${field.min || 0}" max="${field.max || 100}" step="${field.step || 1}">
                        <span class="range-val">${val}</span>
                    </div>
                    ${desc}
                </div>
            `;
        }
        case 'color': {
            const hex = value || '#6c5ce7';
            return `
                <div class="settings-field" data-field="${fieldId}">
                    <label for="field-${fieldId}">${field.label}</label>
                    <input type="color" ${commonAttrs} value="${hex}" style="width:48px;height:32px;padding:2px;border-radius:6px;cursor:pointer">
                    ${desc}
                </div>
            `;
        }
        case 'textarea': {
            return `
                <div class="settings-field" data-field="${fieldId}">
                    <label for="field-${fieldId}">${field.label}</label>
                    <textarea ${commonAttrs} rows="3" placeholder="${field.label}">${escHtml(String(value))}</textarea>
                    ${desc}
                </div>
            `;
        }
        case 'text': {
            const isProviderField = field.key_dynamic && field.key_suffix === 'base_url';
            const actionBtn = isProviderField ? `
                <button class="icon-btn test-conn-btn" onclick="testConnectionFromField('field-${fieldId}')" title="Test connection">
                    <span class="material-icons-round">wifi_find</span>
                </button>
            ` : '';
            return `
                <div class="settings-field" data-field="${fieldId}">
                    <label for="field-${fieldId}">${field.label}</label>
                    <div class="input-with-action">
                        <input type="text" ${commonAttrs} value="${escHtml(String(value))}" placeholder="${field.label}">
                        ${actionBtn}
                    </div>
                    ${desc}
                </div>
            `;
        }
        case 'info': {
            return `
                <div class="settings-field" data-field="${fieldId}">
                    <label>${field.label}</label>
                    <div class="char-info-preview" id="char-info-preview">
                        <div class="skeleton skeleton-text" style="width:60%"></div>
                        <div class="skeleton skeleton-text"></div>
                    </div>
                    ${desc}
                </div>
            `;
        }
    }
}

export function renderCategory(category) {
    if (category === 'Vault') {
        return _renderVaultTab();
    }
    if (category === 'Rules') {
        return _renderRulesTab();
    }
    const catData = SETTINGS_SCHEMA[category];
    if (!catData) return '<p class="settings-no-results">Unknown category</p>';

    let html = `<h3 class="settings-category-title">${category}</h3>`;

    for (const [fieldId, field] of Object.entries(catData.fields)) {
        if (!_shouldShowField(fieldId, field)) continue;
        html += renderField(fieldId, field);
    }

    html += `<button class="save-category-btn" data-category="${category}">
        <span class="material-icons-round">save</span> Save ${category} Settings
    </button>`;

    // Reset section for the Advanced tab
    if (category === 'Advanced') {
        html += `
            <h3 class="settings-category-title" style="margin-top:24px">Reset to Defaults</h3>
            <p class="field-desc">Reset a settings section to its default values. Provider API keys are preserved.</p>
            <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px">
                <button class="btn btn-sm" data-reset="voice">Reset Voice</button>
                <button class="btn btn-sm" data-reset="agent">Reset Agent</button>
                <button class="btn btn-sm" data-reset="ui">Reset UI</button>
                <button class="btn btn-sm btn-danger" data-reset="all">Reset All</button>
            </div>
        `;
    }

    // Memory Graph section
    if (category === 'Memory') {
        html += `
            <h3 class="settings-category-title" style="margin-top:24px">
                Memory Graph
                <button class="icon-btn" id="memory-graph-refresh" title="Refresh graph">
                    <span class="material-icons-round" style="font-size:1rem;">refresh</span>
                </button>
            </h3>
            <p class="field-desc">Visualize your conversations, topics, and memory connections.</p>
            <div id="memory-graph-container" style="width:100%;height:400px;position:relative;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;background:var(--bg);">
                <canvas id="memory-graph-canvas" style="width:100%;height:100%;display:block;"></canvas>
                <div id="memory-graph-tooltip" style="display:none;position:absolute;background:var(--bg-card);color:var(--text);padding:6px 10px;border-radius:6px;font-size:12px;pointer-events:none;border:1px solid var(--border);z-index:10;max-width:220px;box-shadow:0 2px 8px rgba(0,0,0,0.3);"></div>
                <div id="memory-graph-legend" style="position:absolute;bottom:8px;left:8px;display:flex;gap:14px;font-size:11px;color:var(--text-muted);pointer-events:none;">
                    <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--accent);vertical-align:middle;margin-right:4px;"></span>Session</span>
                    <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:var(--warning);vertical-align:middle;margin-right:4px;"></span>Topic</span>
                    <span><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--text-muted);vertical-align:middle;margin-right:4px;"></span>Fact</span>
                </div>
                <div id="memory-graph-empty" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:var(--text-muted);font-size:14px;text-align:center;">
                    <span class="material-icons-round" style="font-size:2rem;display:block;margin:0 auto 8px;">hub</span>
                    No memory data yet.<br>Start chatting to see your memory graph.
                </div>
            </div>
        `;
    }

    return html;
}

export function renderSettings() {
    const container = document.getElementById('settings-body');
    if (!container) return;

    if (!getSettings()) {
        container.innerHTML = `
            <div class="settings-sidebar">
                ${['Character','Provider','Voice','Memory','Vault','Rules','Appearance','Privacy','Advanced'].map(c => `
                    <div class="skeleton" style="height:36px;margin-bottom:4px;border-radius:8px"></div>
                `).join('')}
            </div>
            <div class="settings-content">
                <div class="skeleton skeleton-text" style="width:30%"></div>
                <div class="skeleton skeleton-text"></div>
                <div class="skeleton skeleton-text"></div>
                <div class="skeleton skeleton-text" style="width:50%"></div>
            </div>
        `;
        return;
    }

    const categories = Object.keys(SETTINGS_SCHEMA);
    let sidebarHtml = categories.map(cat => `
        <button class="settings-cat-btn ${cat === activeSettingsTab ? 'active' : ''}"
                data-category="${cat}"
                aria-label="${cat} settings"
                aria-current="${cat === activeSettingsTab ? 'page' : 'false'}">
            <span class="material-icons-round" aria-hidden="true">${SETTINGS_SCHEMA[cat].icon}</span>
            <span>${cat}</span>
        </button>
    `).join('');
    sidebarHtml += `
        <button class="settings-cat-btn ${activeSettingsTab === 'Vault' ? 'active' : ''}"
                data-category="Vault"
                aria-label="Vault files"
                aria-current="${activeSettingsTab === 'Vault' ? 'page' : 'false'}">
            <span class="material-icons-round" aria-hidden="true">folder</span>
            <span>Vault</span>
        </button>
        <button class="settings-cat-btn ${activeSettingsTab === 'Rules' ? 'active' : ''}"
                data-category="Rules"
                aria-label="Rules"
                aria-current="${activeSettingsTab === 'Rules' ? 'page' : 'false'}">
            <span class="material-icons-round" aria-hidden="true">description</span>
            <span>Rules</span>
        </button>`;

    const searchHtml = `
        <div class="settings-search">
            <span class="material-icons-round">search</span>
            <input type="text" id="settings-search-input" placeholder="Search settings...">
        </div>
    `;

    // Destroy memory graph before re-rendering to clean up event listeners and animation
    import('./memory-graph.js').then(mg => mg.destroyMemoryGraph()).catch(e => console.warn('[Settings] Failed to destroy memory graph:', e));

    container.innerHTML = `
        <div class="settings-sidebar">${sidebarHtml}</div>
        <div class="settings-content">
            ${searchHtml}
            <div id="settings-form-area">${renderCategory(activeSettingsTab)}</div>
        </div>
    `;

    // Add search input listener (delegation is used for most, but input needs direct listener)
    const searchInput = document.getElementById('settings-search-input');
    if (searchInput) {
        searchInput.addEventListener('input', filterSettings);
    }

    // Load companion settings when the Character tab is active
    if (activeSettingsTab === 'Character') {
        setTimeout(loadCompanionSettings, 0);
    }
    if (activeSettingsTab === 'Vault') {
        setTimeout(loadVaultList, 0);
    }
    if (activeSettingsTab === 'Rules') {
        setTimeout(loadRules, 0);
    }
    if (activeSettingsTab === 'Memory') {
        setTimeout(() => {
            import('./memory-graph.js').then(mg => mg.initMemoryGraph()).catch(e => console.warn('[Settings] Failed to init memory graph:', e));
        }, 50);
    }
}

export function switchSettingsTab(category) {
    activeSettingsTab = category;
    if (document.getElementById('tab-settings')?.classList.contains('active')) {
        window.location.hash = `settings/${category}`;
    }
    renderSettings();
    _attachSettingsDelegates();
}

export function filterSettings() {
    const query = document.getElementById('settings-search-input')?.value?.toLowerCase() || '';
    const area = document.getElementById('settings-form-area');
    if (!area) return;

    if (!query) {
        area.innerHTML = renderCategory(activeSettingsTab);
        _attachSettingsDelegates();
        return;
    }

    let html = '<h3 class="settings-category-title">Search Results</h3>';
    let found = false;

    for (const [catName, catData] of Object.entries(SETTINGS_SCHEMA)) {
        const matchingFields = Object.entries(catData.fields).filter(
            ([id, f]) => f.label.toLowerCase().includes(query) || id.toLowerCase().includes(query) || (f.description || '').toLowerCase().includes(query)
        );
        if (matchingFields.length > 0) {
            found = true;
            html += `<h4 class="settings-result-category">${escHtml(catName)}</h4>`;
            for (const [fieldId, field] of matchingFields) {
                if (!_shouldShowField(fieldId, field)) continue;
                html += renderField(fieldId, field);
            }
        }
    }

    if (!found) {
        html += '<p class="settings-no-results">No settings found matching "' + escHtml(query) + '"</p>';
    }

    area.innerHTML = html;
    _attachSettingsDelegates();
}

export async function saveCategory(category) {
    const catData = SETTINGS_SCHEMA[category];
    if (!catData) return;

    // Disable save button during save
    const saveBtn = document.querySelector('.save-category-btn');
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.dataset.originalText = saveBtn.innerHTML;
        saveBtn.innerHTML = '<span class="material-icons-round" style="animation:spin 0.8s linear infinite">sync</span> Saving...';
    }

    const changed = {};
    const cachedSettings = getSettings();
    for (const [fieldId, field] of Object.entries(catData.fields)) {
        if (!_shouldShowField(fieldId, field)) continue;
        if (field.type === 'info') continue;
        const input = document.getElementById(`field-${fieldId}`);
        if (!input) continue;

        const key = _getFieldKey(fieldId, field);
        let value;
        if (field.type === 'toggle') {
            value = input.checked;
        } else if (field.type === 'number' || field.type === 'range') {
            value = Number(input.value);
        } else {
            value = input.value;
        }
        // Skip fields whose value matches the cached settings
        const cachedValue = _getNestedValue(cachedSettings, key);
        if (cachedValue !== undefined && value == cachedValue) continue;
        changed[key] = value;
    }

    if (category === 'Provider') {
        const apInput = document.getElementById('field-active_provider');
        if (apInput) {
            changed['provider.active'] = apInput.value;
        }
    }

    try {
        const data = await api(`${BASE_URL}/api/settings/batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ settings: changed }),
        });
        if (data?.status === 'ok') {
            showToast(`${category} settings saved`, 'success');
            const s = await api(`${BASE_URL}/api/settings`);
            if (s) setSettingsCache(s);
        } else {
            showToast(`Failed to save: ${data?.error || 'unknown error'}`, 'danger');
        }
    } catch (e) {
        showToast(`Failed to save: ${e.message || 'network error'}`, 'danger');
    } finally {
        // Re-enable save button
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = saveBtn.dataset.originalText || saveBtn.innerHTML;
        }
    }
}

export function toggleFieldVisibility(id) {
    const inp = document.getElementById(id);
    if (!inp) return;
    const isPassword = inp.type === 'password';
    inp.type = isPassword ? 'text' : 'password';
    const btn = inp.parentElement?.querySelector('.toggle-vis-btn .material-icons-round');
    if (btn) btn.textContent = isPassword ? 'visibility_off' : 'visibility';
}

export async function testConnection(key) {
    const match = key.match(/^provider\.([^.]+)\./);
    const provider = match ? match[1] : null;
    if (!provider) {
        showToast('Cannot determine provider for connection test', 'warning');
        return;
    }
    // Find the button in the DOM since event context may not be available
    const btn = document.querySelector(`[data-key="${CSS.escape(key)}"]`)
        ?.closest('.settings-field')
        ?.querySelector('.test-conn-btn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="material-icons-round" style="animation:spin 1s linear infinite">sync</span>';
    }
    const result = await api(`${BASE_URL}/api/settings/test/${provider}`, { method: 'POST' });
    if (result?.ok) {
        if (btn) btn.innerHTML = '<span class="material-icons-round" style="color:var(--success)">check_circle</span>';
        showToast(`Connected (${result.latency_ms}ms)`, 'success');
    } else {
        if (btn) btn.innerHTML = '<span class="material-icons-round" style="color:var(--danger)">error</span>';
        showToast(`Failed: ${result?.error || 'Connection failed'}`, 'danger');
    }
    setTimeout(() => {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="material-icons-round">wifi_find</span>';
        }
    }, 3000);
}

export function fetchModels(provider) {
    if (!provider) return;
    const btn = document.querySelector(`.fetch-models-btn`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="material-icons-round" style="animation:spin 1s linear infinite">sync</span>';
    }
    fetch(`${BASE_URL}/api/models/${provider}`)
        .then(r => r.json())
        .then(data => {
            if (data?.models?.length) {
                const sel = document.getElementById('field-model');
                if (sel) {
                    sel.innerHTML = '<option value="">Select model...</option>';
                    data.models.forEach(m => {
                        const o = document.createElement('option');
                        o.value = m; o.textContent = m;
                        sel.appendChild(o);
                    });
                    const settings = getSettings() || {};
                    const active = settings.provider?.active || provider;
                    const configuredModel = settings.provider?.[active]?.model;
                    if (configuredModel && data.models.includes(configuredModel)) {
                        sel.value = configuredModel;
                    } else if (data.models.length === 1) {
                        sel.value = data.models[0];
                    }
                }
                if (!btn) showToast(`Found ${data.models.length} models`, 'success');
            } else if (btn) {
                showToast('No models found', 'warning');
            }
        })
        .catch(e => { if (btn) showToast(`Failed to fetch models: ${e.message}`, 'danger'); })
        .finally(() => {
            setTimeout(() => {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<span class="material-icons-round">cloud_sync</span>';
                }
            }, 3000);
        });
}

export async function refreshProviderList() {
    await initProviderData();
    _providerList = Object.keys(PROVIDER_DISPLAY_NAMES).map(id => ({
        value: id,
        label: PROVIDER_DISPLAY_NAMES[id] || id,
    }));
}

export function testVoice() {
    const btn = document.querySelector('.test-voice-btn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="material-icons-round" style="animation:spin 1s linear infinite">sync</span>';
    }
    fetch(`${BASE_URL}/api/tts/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: 'Hello, this is my voice.' }),
    })
    .then(r => r.json())
    .then(result => {
        if (result && result.audio) {
            const audio = new Audio(`data:audio/${result.format || 'wav'};base64,${result.audio}`);
            audio.play().catch(e => showToast(`Playback failed: ${e.message}`, 'danger'));
            if (btn) {
                btn.innerHTML = '<span class="material-icons-round" style="color:var(--success)">check_circle</span>';
                setTimeout(() => {
                    btn.disabled = false;
                    btn.innerHTML = '<span class="material-icons-round">volume_up</span>';
                }, 2000);
            }
        } else {
            showToast(result?.error || 'TTS preview failed', 'danger');
            if (btn) {
                btn.innerHTML = '<span class="material-icons-round" style="color:var(--danger)">error</span>';
                setTimeout(() => {
                    btn.disabled = false;
                    btn.innerHTML = '<span class="material-icons-round">volume_up</span>';
                }, 3000);
            }
        }
    })
    .catch(e => {
        showToast(`TTS preview failed: ${e.message}`, 'danger');
        if (btn) {
            btn.innerHTML = '<span class="material-icons-round" style="color:var(--danger)">error</span>';
            setTimeout(() => {
                btn.disabled = false;
                btn.innerHTML = '<span class="material-icons-round">volume_up</span>';
            }, 3000);
        }
    });
}

export function confirmReset(target) {
    const targetNames = { voice: 'Voice', agent: 'Agent', ui: 'UI', all: 'All Settings' };
    const name = targetNames[target] || target;
    if (!confirm(`Reset ${name} settings to defaults? This cannot be undone.`)) return;
    fetch(`${BASE_URL}/api/settings/reset?target=${target}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'ok') {
                showToast(`${name} settings reset to defaults`, 'success');
                fetch(`${BASE_URL}/api/settings`).then(r => r.json()).then(s => {
                    if (s) setSettingsCache(s);
                    renderSettings();
                    _attachSettingsDelegates();
                }).catch(() => {});
            } else {
                showToast(`Reset failed: ${data.error || 'unknown error'}`, 'danger');
            }
        })
        .catch(e => showToast(`Reset failed: ${e.message}`, 'danger'));
}

export async function loadCompanionSettings() {
    const data = await api(`${BASE_URL}/api/companion/settings`);
    if (!data) return;
    const fieldMap = {
        enabled: 'companion_enabled',
        idle_check_delay: 'companion_idle_check_delay',
        proactive_interval: 'companion_proactive_interval',
        time_awareness: 'companion_time_awareness',
        personality_notes: 'companion_personality_notes',
    };
    for (const [apiKey, fieldId] of Object.entries(fieldMap)) {
        const el = document.getElementById(`field-${fieldId}`);
        if (!el) continue;
        const val = data[apiKey];
        if (el.type === 'checkbox') {
            el.checked = val === true;
        } else if (el.type === 'number') {
            el.value = val ?? '';
        } else {
            el.value = val ?? '';
        }
    }
}

export async function refreshCharacterList() {
    try {
        const r = await fetch(`${BASE_URL}/api/characters`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const chars = await r.json();
        _charList = Object.entries(chars || {}).map(([id, c]) => ({
            value: id,
            label: c.name || id,
        }));
        return chars;
    } catch (e) {
        _charList = [];
        return {};
    }
}

export async function refreshCharacterInfo() {
    const preview = document.getElementById('char-info-preview');
    if (!preview) return;
    try {
        const charsR = await api(BASE_URL + '/api/characters');
        const sR = getSettings() || await api(BASE_URL + '/api/settings');
        if (!charsR || !sR) {
            preview.innerHTML = '<span class="muted">Could not load character info</span>';
            return;
        }
        const activeId = sR?.character?.active || 'amalgam';
        const c = charsR?.[activeId];
        if (c) {
            const desc = escHtml(c.description || 'No description');
            const personality = escHtml(c.personality || '');
            const voice = c.voice ? escHtml(String(c.voice).split('-').pop().replace('Neural', '')) : 'default';
            preview.innerHTML = `
                <div class="char-info-row"><span class="char-info-label">Name</span><span>${escHtml(c.name || activeId)}</span></div>
                ${personality ? `<div class="char-info-row"><span class="char-info-label">Personality</span><span>${personality}</span></div>` : ''}
                <div class="char-info-row"><span class="char-info-label">Voice</span><span>${voice}</span></div>
                <div class="char-info-desc">${desc}</div>
            `;
        } else {
            preview.innerHTML = '<span class="muted">No character selected</span>';
        }
    } catch (e) {
        console.warn('[Settings] Character info load failed:', e);
        preview.innerHTML = '<span class="muted">Could not load character info</span>';
    }
}

// ─── Vault Tab ────────────────────────────────────────────────────────

function _formatBytes(bytes) {
    if (!bytes && bytes !== 0) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function _formatDate(ts) {
    if (!ts) return '';
    try { return new Date(ts).toLocaleDateString(); }
    catch (_) { return String(ts); }
}

function _renderVaultTab() {
    return `
        <div id="vault-tab" class="vault-tab">
            <div class="vault-toolbar">
                <div class="settings-search" style="flex:1;margin-bottom:0">
                    <span class="material-icons-round">search</span>
                    <input type="text" id="vault-search-input" placeholder="${escHtml(t('settings.vault_search_placeholder'))}">
                </div>
                <button class="btn-sm" id="vault-new-btn" style="display:flex;align-items:center;gap:4px;white-space:nowrap">
                    <span class="material-icons-round" style="font-size:16px">add</span>
                    ${escHtml(t('settings.new'))}
                </button>
            </div>
            <div id="vault-body"></div>
        </div>
    `;
}

export async function loadVaultList() {
    const body = document.getElementById('vault-body');
    if (!body) return;
    _currentVaultFile = null;
    body.innerHTML = '<div class="vault-loading"><div class="skeleton" style="height:40px;margin-bottom:4px;border-radius:8px"></div>'.repeat(3) + '</div>';

    const data = await api(`${BASE_URL}/api/vault/files`);
    if (!data || !data.files) {
        body.innerHTML = `<p class="muted vault-empty">${escHtml(t('vault.no_files'))}</p>`;
        return;
    }

    _vaultFiles = data.files;
    _renderVaultFileList(body);
}

function _renderVaultFileList(container) {
    if (_vaultFiles.length === 0) {
        container.innerHTML = `<p class="muted vault-empty">${escHtml(t('vault.no_files'))}</p>`;
        return;
    }

    container.innerHTML = _vaultFiles.map(f => {
        const name = escHtml(f.name);
        const size = _formatBytes(f.size);
        const modified = f.modified ? _formatDate(f.modified) : '';
        const bytesLabel = t('vault.bytes', { size });
        return `
            <div class="vault-file-item" data-vault-file="${escHtml(f.name)}">
                <span class="material-icons-round vault-file-icon">description</span>
                <div class="vault-file-info">
                    <div class="vault-file-name">${name}</div>
                    <div class="vault-file-meta">${escHtml(bytesLabel)}${modified ? ' &middot; ' + escHtml(modified) : ''}</div>
                </div>
                <button class="vault-file-delete" data-vault-file-delete="${escHtml(f.name)}" title="Delete">
                    <span class="material-icons-round">delete</span>
                </button>
            </div>
        `;
    }).join('');
}

export function showVaultList() {
    _currentVaultFile = null;
    loadVaultList();
}

export async function viewVaultFile(filename) {
    const body = document.getElementById('vault-body');
    if (!body) return;
    _currentVaultFile = filename;

    body.innerHTML = `
        <div class="vault-editor-header">
            <button class="btn-ghost vault-back-btn">
                <span class="material-icons-round">arrow_back</span>
                Back
            </button>
            <span class="vault-editor-filename">${escHtml(filename)}</span>
        </div>
        <div class="skeleton" style="height:200px;margin-top:8px;border-radius:8px"></div>
    `;

    const data = await api(`${BASE_URL}/api/vault/files/${encodeURIComponent(filename)}`);
    if (!data) {
        body.innerHTML = '<p class="muted vault-empty">Failed to load file</p>';
        return;
    }

    body.innerHTML = `
        <div class="vault-editor-header">
            <button class="btn-ghost vault-back-btn">
                <span class="material-icons-round">arrow_back</span>
                Back
            </button>
            <span class="vault-editor-filename">${escHtml(data.name || filename)}</span>
        </div>
        <textarea id="vault-editor-textarea" class="vault-editor-textarea" rows="20">${escHtml(data.content || '')}</textarea>
        <div class="vault-editor-actions">
            <button class="save-category-btn vault-save-btn">
                <span class="material-icons-round">save</span> ${escHtml(t('settings.save'))}
            </button>
            <button class="btn btn-danger vault-delete-btn">
                <span class="material-icons-round">delete</span> ${escHtml(t('settings.delete'))}
            </button>
        </div>
    `;
}

export async function saveVaultFile() {
    if (!_currentVaultFile) return;
    const textarea = document.getElementById('vault-editor-textarea');
    if (!textarea) return;
    const data = await api(`${BASE_URL}/api/vault/files/${encodeURIComponent(_currentVaultFile)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: textarea.value }),
    });
    if (data?.status === 'ok') {
        showToast(t('toast.file_saved'), 'success');
    } else {
        showToast('Failed to save file', 'danger');
    }
}

export async function deleteCurrentVaultFile() {
    if (!_currentVaultFile) return;
    await _deleteVaultFile(_currentVaultFile);
}

export async function deleteVaultFile(filename) {
    await _deleteVaultFile(filename);
}

async function _deleteVaultFile(filename) {
    if (!confirm(t('confirm.delete_file', { filename }))) return;
    const data = await api(`${BASE_URL}/api/vault/files/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
    });
    if (data?.status === 'ok') {
        showToast(t('toast.file_deleted'), 'success');
        showVaultList();
    } else {
        showToast('Failed to delete file', 'danger');
    }
}

export async function newVaultFile() {
    const filename = prompt(t('toast.enter_filename'));
    if (!filename) return;
    let finalName = filename.trim();
    if (!finalName.endsWith('.md')) {
        if (!confirm(t('toast.filename_md'))) return;
        finalName += '.md';
    }
    viewVaultFile(finalName);
}

export async function searchVault() {
    const input = document.getElementById('vault-search-input');
    if (!input) return;
    const query = input.value.trim();
    const body = document.getElementById('vault-body');
    if (!body) return;

    if (document.getElementById('vault-editor-textarea')) return; // don't search while editing

    if (!query) {
        _renderVaultFileList(body);
        return;
    }

    body.innerHTML = '<div class="vault-loading"><div class="skeleton" style="height:40px;margin-bottom:4px;border-radius:8px"></div>'.repeat(3) + '</div>';

    const data = await api(`${BASE_URL}/api/vault/search?q=${encodeURIComponent(query)}`);
    if (!data || !data.results) {
        body.innerHTML = '<p class="muted vault-empty">Search failed</p>';
        return;
    }

    if (data.results.length === 0) {
        body.innerHTML = '<p class="muted vault-empty">No results found</p>';
        return;
    }

    const modeLabel = data.mode === 'semantic' ? t('settings.semantic') : 'Keyword';
    body.innerHTML = `
        <p class="vault-search-info">${escHtml(modeLabel)} &middot; ${data.results.length} results</p>
        ${data.results.map(r => {
            const name = escHtml(r.filename || r.name || 'unknown');
            const snippet = escHtml((r.snippet || r.content || '').substring(0, 200));
            return `
                <div class="vault-file-item" data-vault-file="${escHtml(r.filename || r.name)}">
                    <span class="material-icons-round vault-file-icon">description</span>
                    <div class="vault-file-info">
                        <div class="vault-file-name">${name}</div>
                        <div class="vault-file-meta vault-file-snippet">${snippet}</div>
                    </div>
                </div>
            `;
        }).join('')}
    `;
}

// ─── Rules Tab ────────────────────────────────────────────────────────

function _renderRulesTab() {
    return `
        <div id="rules-tab" class="rules-tab">
            <h3 class="settings-category-title">${escHtml(t('settings.persistent_rules'))}</h3>
            <p class="field-desc">This file contains persistent system prompt rules that are prepended to every conversation. Changes take effect on the next message.</p>
            <textarea id="rules-textarea" class="vault-editor-textarea" rows="20" placeholder="${escHtml(t('settings.rules_placeholder'))}"></textarea>
            <button class="save-category-btn rules-save-btn" style="align-self:flex-start">
                <span class="material-icons-round">save</span> ${escHtml(t('settings.save_rules'))}
            </button>
        </div>
    `;
}

export async function loadRules() {
    const textarea = document.getElementById('rules-textarea');
    if (!textarea) return;
    textarea.value = 'Loading...';
    textarea.disabled = true;
    const data = await api(`${BASE_URL}/api/rules`);
    if (data && data.content !== undefined) {
        textarea.value = data.content;
    } else {
        textarea.value = '';
        showToast('Failed to load rules', 'warning');
    }
    textarea.disabled = false;
}

export async function saveRules() {
    const textarea = document.getElementById('rules-textarea');
    if (!textarea) return;
    const data = await api(`${BASE_URL}/api/rules`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: textarea.value }),
    });
    if (data?.status === 'ok') {
        showToast(t('toast.rules_saved'), 'success');
    } else {
        showToast('Failed to save rules', 'danger');
    }
}

// Delegate event handlers (change + input)
let _delegatesAttached = false;
export function _attachSettingsDelegates() {
    const body = document.getElementById('settings-body');
    if (!body) return;
    if (_delegatesAttached) return;
    _delegatesAttached = true;

    // Delegate fetch-models-btn clicks (avoid inline onclick with user-controlled provider)
    body.addEventListener('click', (e) => {
        const fetchBtn = e.target.closest('.fetch-models-btn');
        if (fetchBtn) {
            e.preventDefault();
            fetchModels(fetchBtn.dataset.provider);
            return;
        }
        const testConnBtn = e.target.closest('.test-conn-btn');
        if (testConnBtn) {
            e.preventDefault();
            const key = testConnBtn.closest('.settings-field')?.querySelector('[data-key]')?.dataset?.key;
            if (key) testConnection(key);
            return;
        }
        const testVoiceBtn = e.target.closest('.test-voice-btn');
        if (testVoiceBtn) {
            e.preventDefault();
            testVoice();
            return;
        }
        const toggleVisBtn = e.target.closest('.toggle-vis-btn');
        if (toggleVisBtn) {
            e.preventDefault();
            const inp = toggleVisBtn.parentElement?.querySelector('input');
            if (inp) toggleFieldVisibility(inp.id);
            return;
        }
        const saveCatBtn = e.target.closest('.save-category-btn');
        if (saveCatBtn) {
            e.preventDefault();
            const category = saveCatBtn.dataset.category || activeSettingsTab;
            saveCategory(category);
            return;
        }
        const resetBtn = e.target.closest('[data-reset]');
        if (resetBtn) {
            e.preventDefault();
            confirmReset(resetBtn.dataset.reset);
            return;
        }
        const catBtn = e.target.closest('.settings-cat-btn[data-category]');
        if (catBtn) {
            e.preventDefault();
            switchSettingsTab(catBtn.dataset.category);
            return;
        }
        const vaultBackBtn = e.target.closest('.vault-back-btn');
        if (vaultBackBtn) {
            e.preventDefault();
            showVaultList();
            return;
        }
        const vaultSaveBtn = e.target.closest('.vault-save-btn');
        if (vaultSaveBtn) {
            e.preventDefault();
            saveVaultFile();
            return;
        }
        const vaultDeleteBtn = e.target.closest('.vault-delete-btn');
        if (vaultDeleteBtn) {
            e.preventDefault();
            deleteCurrentVaultFile();
            return;
        }
        const vaultNewBtn = e.target.closest('#vault-new-btn');
        if (vaultNewBtn) {
            e.preventDefault();
            newVaultFile();
            return;
        }
        const rulesSaveBtn = e.target.closest('.rules-save-btn');
        if (rulesSaveBtn) {
            e.preventDefault();
            saveRules();
            return;
        }
        const fileItem = e.target.closest('[data-vault-file]');
        if (fileItem && !e.target.closest('[data-vault-file-delete]')) {
            viewVaultFile(fileItem.dataset.vaultFile);
            return;
        }
        const delBtn = e.target.closest('[data-vault-file-delete]');
        if (delBtn) {
            deleteVaultFile(delBtn.dataset.vaultFileDelete);
        }
    });

    body.addEventListener('change', (e) => {
        const el = e.target;
        const fieldId = el.dataset?.field || el.id?.replace('field-', '') || '';

        if (fieldId === 'theme') applyTheme(el.value);
        if (fieldId === 'language') {
            const lang = el.value;
            if (typeof t === 'function') { /* i18n handled externally */ }
            fetch(`${BASE_URL}/api/settings/set`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'ui.language', value: lang })
            }).catch(() => {});
        }
        if (fieldId === 'accent_color') applyAccentColor(el.value);
        if (fieldId === 'font_size') {
            const val = el.value;
            const rv = body.querySelector('.range-val');
            if (rv) rv.textContent = val + 'px';
            document.documentElement.style.setProperty('--font-size', val + 'px');
        }
        if (fieldId === 'temperature') {
            const rv = body.querySelector('.range-val');
            if (rv) rv.textContent = el.value;
        }

        if (fieldId === 'stt_engine' || fieldId === 'tts_engine' || fieldId === 'active_provider') {
            const area = document.getElementById('settings-form-area');
            if (area && !document.getElementById('settings-search-input')?.value) {
                area.innerHTML = renderCategory(activeSettingsTab);
                _delegatesAttached = false;
                _attachSettingsDelegates();
            }
            if (fieldId === 'active_provider') {
                setTimeout(() => fetchModels(el.value), 50);
            }
        }

        if (fieldId === 'voice_input') {
            const headerToggle = document.getElementById('voice-input-toggle');
            if (headerToggle) {
                const enabled = el.checked;
                headerToggle.querySelector('.material-icons-round').textContent = enabled ? 'mic' : 'mic_off';
                headerToggle.classList.toggle('active', enabled);
                if (typeof window._toggleVoiceInputState === 'function') {
                    window._toggleVoiceInputState(enabled);
                }
            }
        }
        if (fieldId === 'voice_output') {
            const headerToggle = document.getElementById('voice-output-toggle');
            if (headerToggle) {
                const enabled = el.checked;
                headerToggle.querySelector('.material-icons-round').textContent = enabled ? 'volume_up' : 'volume_off';
                headerToggle.classList.toggle('active', enabled);
            }
        }
    });

    body.addEventListener('input', (e) => {
        if (e.target.type === 'range') {
            const rv = e.target.parentElement?.querySelector('.range-val');
            if (rv) {
                const suffix = e.target.dataset?.field === 'font_size' ? 'px' : '';
                rv.textContent = e.target.value + suffix;
            }
        }
    });

    // Vault file item click delegation
    body.addEventListener('click', (e) => {
        const fileItem = e.target.closest('[data-vault-file]');
        if (fileItem && !e.target.closest('[data-vault-file-delete]')) {
            viewVaultFile(fileItem.dataset.vaultFile);
            return;
        }
        const delBtn = e.target.closest('[data-vault-file-delete]');
        if (delBtn) {
            deleteVaultFile(delBtn.dataset.vaultFileDelete);
        }
    });
}

// Expose to window for onclick handlers in generated HTML
window.switchSettingsTab = switchSettingsTab;
window.filterSettings = filterSettings;
window.saveCategory = saveCategory;
window.toggleFieldVisibility = toggleFieldVisibility;
window.testConnection = testConnection;
window.fetchModels = fetchModels;
window.testVoice = testVoice;
window.confirmReset = confirmReset;
window.loadCompanionSettings = loadCompanionSettings;
window.testConnectionFromField = function(fieldId) {
    const inp = document.getElementById(fieldId);
    if (!inp) return;
    const key = inp.dataset.key || '';
    testConnection(key);
};

// Vault & Rules window exports
window.loadVaultList = loadVaultList;
window.viewVaultFile = viewVaultFile;
window.showVaultList = showVaultList;
window.saveVaultFile = saveVaultFile;
window.deleteVaultFile = deleteVaultFile;
window.deleteCurrentVaultFile = deleteCurrentVaultFile;
window.newVaultFile = newVaultFile;
window.searchVault = searchVault;
window.loadRules = loadRules;
window.saveRules = saveRules;

// Settings open/close (tab-based)
window.openSettings = function() {
    const btn = document.querySelector('.nav-item[data-tab="settings"]');
    if (btn) {
        btn.click();
        setTimeout(() => {
            const body = document.getElementById('settings-body');
            if (body) {
                const fb = body.querySelector('button, [href], input, select, textarea');
                if (fb) fb.focus();
            }
        }, 150);
    }
};

window.closeSettings = function() {
    const btn = document.querySelector('.nav-item[data-tab="chat"]');
    if (btn) {
        btn.click();
        setTimeout(() => {
            const input = document.getElementById('chat-input');
            if (input) input.focus();
        }, 100);
    }
};
