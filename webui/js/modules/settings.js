/**
 * settings.js — Settings panel rendering and management
 */
import { BASE_URL } from './config.js';
import { escapeHtml, _getNestedValue, showToast, applyTheme, applyAccentColor } from './utils.js';
import { api } from './api-client.js';
import { PROVIDER_DISPLAY_NAMES, PROVIDER_MODELS, SETTINGS_SCHEMA } from './settings-schema.js';
import { getSettings, setSettingsCache } from './state.js';
import { t } from '../i18n.js';

let activeSettingsTab = 'Character';
let _providerList = null;
let _charList = null;

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
    const desc = field.description ? `<span class="field-desc">${escapeHtml(field.description)}</span>` : '';
    const commonAttrs = `id="field-${fieldId}" data-key="${escapeHtml(key)}" data-field="${fieldId}"`;

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
                return `<option value="${escapeHtml(val)}" ${String(value) === val ? 'selected' : ''}>${escapeHtml(label)}</option>`;
            }).join('');
            let actionBtn = '';
            if (field.dynamic_options) {
                const active = _getNestedValue(settings, 'provider.active') || 'gemini';
                actionBtn = `<button class="icon-btn fetch-models-btn" onclick="fetchModels('${active}')" title="Fetch models from provider">
                    <span class="material-icons-round">cloud_sync</span>
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
                        <input type="password" ${commonAttrs} value="${escapeHtml(String(value))}" placeholder="${field.label}">
                        <button class="icon-btn toggle-vis-btn" onclick="toggleFieldVisibility('field-${fieldId}')" title="Show/hide">
                            <span class="material-icons-round">visibility</span>
                        </button>
                        <button class="icon-btn test-conn-btn" onclick="testConnection('${escapeHtml(key)}')" title="Test connection">
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
                    <input type="number" ${commonAttrs} value="${escapeHtml(String(value))}" min="${field.min || 0}" max="${field.max || 999}" step="${field.step || 1}">
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
                    <textarea ${commonAttrs} rows="3" placeholder="${field.label}">${escapeHtml(String(value))}</textarea>
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
                        <input type="text" ${commonAttrs} value="${escapeHtml(String(value))}" placeholder="${field.label}">
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
    const catData = SETTINGS_SCHEMA[category];
    if (!catData) return '<p class="settings-no-results">Unknown category</p>';

    let html = `<h3 class="settings-category-title">${category}</h3>`;

    for (const [fieldId, field] of Object.entries(catData.fields)) {
        if (!_shouldShowField(fieldId, field)) continue;
        html += renderField(fieldId, field);
    }

    html += `<button class="save-category-btn" onclick="saveCategory('${category}')">
        <span class="material-icons-round">save</span> Save ${category} Settings
    </button>`;

    return html;
}

export function renderSettings() {
    const container = document.getElementById('settings-body');
    if (!container) return;

    if (!getSettings()) {
        container.innerHTML = `
            <div class="settings-sidebar">
                ${['Character','Provider','Voice','Memory','Appearance','Privacy','Advanced'].map(c => `
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
                onclick="switchSettingsTab('${cat}')"
                aria-label="${cat} settings"
                aria-current="${cat === activeSettingsTab ? 'page' : 'false'}">
            <span class="material-icons-round" aria-hidden="true">${SETTINGS_SCHEMA[cat].icon}</span>
            <span>${cat}</span>
        </button>
    `).join('');

    const searchHtml = `
        <div class="settings-search">
            <span class="material-icons-round">search</span>
            <input type="text" id="settings-search-input" placeholder="Search settings..." oninput="filterSettings()">
        </div>
    `;

    container.innerHTML = `
        <div class="settings-sidebar">${sidebarHtml}</div>
        <div class="settings-content">
            ${searchHtml}
            <div id="settings-form-area">${renderCategory(activeSettingsTab)}</div>
        </div>
    `;
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
            html += `<h4 class="settings-result-category">${escapeHtml(catName)}</h4>`;
            for (const [fieldId, field] of matchingFields) {
                if (!_shouldShowField(fieldId, field)) continue;
                html += renderField(fieldId, field);
            }
        }
    }

    if (!found) {
        html += '<p class="settings-no-results">No settings found matching "' + escapeHtml(query) + '"</p>';
    }

    area.innerHTML = html;
    _attachSettingsDelegates();
}

export function saveCategory(category) {
    const catData = SETTINGS_SCHEMA[category];
    if (!catData) return;

    const changed = {};
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
        changed[key] = value;
    }

    if (category === 'Provider') {
        const apInput = document.getElementById('field-active_provider');
        if (apInput) {
            changed['provider.active'] = apInput.value;
        }
    }

    fetch(`${BASE_URL}/api/settings/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: changed }),
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'ok') {
            showToast(`${category} settings saved`, 'success');
            fetch(`${BASE_URL}/api/settings`).then(r => r.json()).then(s => {
                setSettingsCache(s);
            }).catch(() => {});
        } else {
            showToast(`Failed to save: ${data.error || 'unknown error'}`, 'danger');
        }
    })
    .catch(e => showToast(`Save failed: ${e.message}`, 'danger'));
}

export function toggleFieldVisibility(id) {
    const inp = document.getElementById(id);
    if (!inp) return;
    const isPassword = inp.type === 'password';
    inp.type = isPassword ? 'text' : 'password';
    const btn = inp.parentElement?.querySelector('.toggle-vis-btn .material-icons-round');
    if (btn) btn.textContent = isPassword ? 'visibility_off' : 'visibility';
}

export function testConnection(key) {
    const match = key.match(/^provider\.([^.]+)\./);
    const provider = match ? match[1] : null;
    if (!provider) {
        showToast('Cannot determine provider for connection test', 'warning');
        return;
    }
    const btn = event?.target?.closest?.('.test-conn-btn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="material-icons-round" style="animation:spin 1s linear infinite">sync</span>';
    }
    fetch(`${BASE_URL}/api/settings/test/${provider}`, { method: 'POST' })
        .then(r => r.json())
        .then(result => {
            if (result.ok) {
                if (btn) btn.innerHTML = '<span class="material-icons-round" style="color:var(--success)">check_circle</span>';
                showToast(`Connected (${result.latency_ms}ms)`, 'success');
            } else {
                if (btn) btn.innerHTML = '<span class="material-icons-round" style="color:var(--danger)">error</span>';
                showToast(`Failed: ${result.error}`, 'danger');
            }
        })
        .catch(e => {
            if (btn) btn.innerHTML = '<span class="material-icons-round" style="color:var(--danger)">error</span>';
            showToast(`Connection test failed: ${e.message}`, 'danger');
        })
        .finally(() => {
            setTimeout(() => {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<span class="material-icons-round">wifi_find</span>';
                }
            }, 3000);
        });
}

export function fetchModels(provider) {
    if (!provider) return;
    const btn = event?.target?.closest?.('.fetch-models-btn');
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
    try {
        const resp = await fetch(`${BASE_URL}/api/providers`);
        const data = await resp.json();
        _providerList = (data.providers || []).map(p => ({
            value: p.id,
            label: PROVIDER_DISPLAY_NAMES[p.id] || p.name || p.id,
        }));
    } catch (e) {
        _providerList = Object.keys(PROVIDER_DISPLAY_NAMES).map(id => ({
            value: id,
            label: PROVIDER_DISPLAY_NAMES[id] || id,
        }));
    }
}

export async function refreshCharacterList() {
    try {
        const r = await fetch(`${BASE_URL}/api/characters`);
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
            const { escHtml: eH } = await import('./utils.js');
            const desc = eH(c.description || 'No description');
            const personality = eH(c.personality || '');
            const voice = c.voice ? eH(String(c.voice).split('-').pop().replace('Neural', '')) : 'default';
            preview.innerHTML = `
                <div class="char-info-row"><span class="char-info-label">Name</span><span>${eH(c.name || activeId)}</span></div>
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

// Delegate event handlers (change + input)
let _delegatesAttached = false;
export function _attachSettingsDelegates() {
    const body = document.getElementById('settings-body');
    if (!body) return;
    if (_delegatesAttached) return;
    _delegatesAttached = true;

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
}

// Expose to window for onclick handlers in generated HTML
window.switchSettingsTab = switchSettingsTab;
window.filterSettings = filterSettings;
window.saveCategory = saveCategory;
window.toggleFieldVisibility = toggleFieldVisibility;
window.testConnection = testConnection;
window.fetchModels = fetchModels;
window.testConnectionFromField = function(fieldId) {
    const inp = document.getElementById(fieldId);
    if (!inp) return;
    const key = inp.dataset.key || '';
    testConnection(key);
};

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
