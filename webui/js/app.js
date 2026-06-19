
const IS_TAURI = window.location.protocol === 'tauri:' || window.location.protocol === 'asset:';
document.addEventListener('keydown', e => {
    if ((e.ctrlKey && (e.key === 'q' || e.key === 'd'))) {
        e.preventDefault();
        if (window.__TAURI__) { window.__TAURI__.core.invoke('exit_app'); }
    }
});
const BASE_URL = IS_TAURI ? 'http://localhost:8000' : '';
function _deriveWsUrl() {
    if (IS_TAURI) return 'ws://localhost:8000';
    const loc = window.location;
    const wsProto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    let wsPort = loc.port || (loc.protocol === 'https:' ? '443' : '80');
    // Dev servers (Vite, etc.) serve the page on a different port than the backend.
    // Fall back to the backend port so the WebSocket connects to the right process.
    const DEV_SERVER_PORTS = new Set(['5173', '3000', '5174', '5175', '4173']);
    if (DEV_SERVER_PORTS.has(wsPort)) {
        wsPort = '8000';
    }
    return `${wsProto}//${loc.hostname}:${wsPort}`;
}
const WS_BASE = _deriveWsUrl();

import { initCustomSelects, syncAllCustomSelects } from './custom-select.js';
import { t, setLanguage, initI18n, getCurrentLang } from './i18n.js';
import { loadMetrics, initMetricsAutoRefresh } from './metrics.js';


let avatarRenderer = null;
let avatarPreviewRenderer = null;
let speechBubble = null;

window.addEventListener('error', e => console.error('GLOBAL_ERROR:', e.message, e.filename, e.lineno));

// ============================================================
// SETTINGS SCHEMA — data-driven settings form definitions
// ============================================================

const SETTINGS_SCHEMA = {
    "Provider": {
        icon: "cloud",
        fields: {
            active_provider: {
                label: "Active Provider",
                type: "select",
                key: "provider.active",
                options: ["gemini", "ollama", "openrouter", "zai", "siliconflow", "groq", "chatgpt", "claude", "llamacpp", "koboldai", "deepseek", "mistral", "together", "azure-openai", "alibaba", "huggingface", "aws", "gcp"],
                description: "Which LLM provider to use for responses",
                onChange: "refreshCategory",
            },
            api_key: {
                label: "API Key",
                type: "password",
                key_dynamic: true,
                key_suffix: "api_key",
                description: "Your API key for the active provider",
                show_if: { field: "active_provider", not_in: ["ollama", "llamacpp", "koboldai"] },
            },
            model: {
                label: "Model",
                type: "select",
                key_dynamic: true,
                key_suffix: "model",
                dynamic_options: true,
                description: "Model to use for the active provider",
            },
            base_url: {
                label: "Base URL",
                type: "text",
                key_dynamic: true,
                key_suffix: "base_url",
                description: "Custom API endpoint base URL",
            },
            // AWS-specific
            aws_access_key: {
                label: "AWS Access Key ID",
                type: "password",
                key: "provider.aws.access_key",
                show_if: { field: "active_provider", equals: "aws" },
                description: "AWS access key for Bedrock",
            },
            aws_secret_key: {
                label: "AWS Secret Access Key",
                type: "password",
                key: "provider.aws.secret_key",
                show_if: { field: "active_provider", equals: "aws" },
            },
            aws_region: {
                label: "AWS Region",
                type: "text",
                key: "provider.aws.region",
                show_if: { field: "active_provider", equals: "aws" },
            },
            // GCP-specific
            gcp_service_account: {
                label: "GCP Service Account JSON",
                type: "textarea",
                key: "provider.gcp.service_account_json",
                show_if: { field: "active_provider", equals: "gcp" },
                description: "Paste your service account JSON key",
            },
            gcp_project_id: {
                label: "GCP Project ID",
                type: "text",
                key: "provider.gcp.project_id",
                show_if: { field: "active_provider", equals: "gcp" },
            },
            gcp_region: {
                label: "GCP Region",
                type: "text",
                key: "provider.gcp.region",
                show_if: { field: "active_provider", equals: "gcp" },
            },
            // Model spec for AWS/GCP
            aws_model: {
                label: "Model",
                type: "select",
                key: "provider.aws.model",
                show_if: { field: "active_provider", equals: "aws" },
                options: ["anthropic.claude-sonnet-4-20250514", "anthropic.claude-3-5-sonnet-20241022", "meta.llama3-70b-instruct-v1:0"],
                description: "Bedrock model ID",
            },
            gcp_model: {
                label: "Model",
                type: "select",
                key: "provider.gcp.model",
                show_if: { field: "active_provider", equals: "gcp" },
                options: ["gemini-2.0-flash-001", "gemini-2.5-flash-001", "gemini-2.5-pro-001"],
                description: "Vertex AI model name",
            },
        }
    },
    "Voice": {
        icon: "record_voice_over",
        fields: {
            stt_engine: {
                label: "Speech-to-Text Engine",
                type: "select",
                key: "voice.stt_engine",
                options: ["browser", "faster-whisper", "openai-whisper", "groq-whisper", "whispercpp"],
                description: "Engine for converting speech to text",
                onChange: "refreshCategory",
            },
            tts_engine: {
                label: "Text-to-Speech Engine",
                type: "select",
                key: "voice.engine",
                options: ["edge-tts", "openvoice", "elevenlabs", "openai-tts", "speecht5", "alltalk", "piper", "coqui-local", "kokoro"],
                description: "Engine for converting text to speech",
                onChange: "refreshCategory",
            },
            voice_input: {
                label: "Voice Input (Mic)",
                type: "toggle",
                key: "voice.input_enabled",
                description: "Enable microphone input",
            },
            voice_output: {
                label: "Voice Output (Speaker)",
                type: "toggle",
                key: "voice.output_enabled",
                description: "Enable speech output",
            },
            lipsync: {
                label: "Lip-sync",
                type: "toggle",
                key: "voice.lipsync_enabled",
                description: "Animate avatar mouth with speech",
            },
            // Faster-Whisper sub-fields
            fw_model: {
                label: "Faster-Whisper Model Size",
                type: "select",
                key: "voice.faster_whisper.model",
                options: ["tiny", "base", "small", "medium", "large"],
                show_if: { field: "stt_engine", equals: "faster-whisper" },
            },
            // OpenAI Whisper sub-fields
            ow_api_key: {
                label: "OpenAI Whisper API Key",
                type: "password",
                key: "voice.openai_whisper.api_key",
                show_if: { field: "stt_engine", equals: "openai-whisper" },
            },
            ow_model: {
                label: "OpenAI Whisper Model",
                type: "text",
                key: "voice.openai_whisper.model",
                show_if: { field: "stt_engine", equals: "openai-whisper" },
            },
            // Groq Whisper sub-fields
            gw_api_key: {
                label: "Groq Whisper API Key",
                type: "password",
                key: "voice.groq_whisper.api_key",
                show_if: { field: "stt_engine", equals: "groq-whisper" },
            },
            gw_model: {
                label: "Groq Whisper Model",
                type: "text",
                key: "voice.groq_whisper.model",
                show_if: { field: "stt_engine", equals: "groq-whisper" },
            },
            gw_base_url: {
                label: "Groq Whisper Base URL",
                type: "text",
                key: "voice.groq_whisper.base_url",
                show_if: { field: "stt_engine", equals: "groq-whisper" },
            },
            // Whisper.cpp
            wcpp_url: {
                label: "Whisper.cpp URL",
                type: "text",
                key: "voice.whispercpp.url",
                show_if: { field: "stt_engine", equals: "whispercpp" },
            },
            // ElevenLabs sub-fields
            el_api_key: {
                label: "ElevenLabs API Key",
                type: "password",
                key: "voice.elevenlabs.api_key",
                show_if: { field: "tts_engine", equals: "elevenlabs" },
            },
            el_voice_id: {
                label: "ElevenLabs Voice ID",
                type: "text",
                key: "voice.elevenlabs.voice_id",
                show_if: { field: "tts_engine", equals: "elevenlabs" },
            },
            // OpenAI TTS sub-fields
            otts_api_key: {
                label: "OpenAI TTS API Key",
                type: "password",
                key: "voice.openai_tts.api_key",
                show_if: { field: "tts_engine", equals: "openai-tts" },
            },
            otts_model: {
                label: "OpenAI TTS Model",
                type: "text",
                key: "voice.openai_tts.model",
                show_if: { field: "tts_engine", equals: "openai-tts" },
            },
            otts_voice: {
                label: "OpenAI TTS Voice",
                type: "select",
                key: "voice.openai_tts.voice",
                options: ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
                show_if: { field: "tts_engine", equals: "openai-tts" },
            },
            // AllTalk
            at_url: {
                label: "AllTalk URL",
                type: "text",
                key: "voice.alltalk.url",
                show_if: { field: "tts_engine", equals: "alltalk" },
            },
            at_voice: {
                label: "AllTalk Voice",
                type: "text",
                key: "voice.alltalk.voice",
                show_if: { field: "tts_engine", equals: "alltalk" },
            },
            at_language: {
                label: "AllTalk Language",
                type: "text",
                key: "voice.alltalk.language",
                show_if: { field: "tts_engine", equals: "alltalk" },
            },
            at_version: {
                label: "AllTalk Version",
                type: "select",
                key: "voice.alltalk.version",
                options: ["v2", "v1"],
                show_if: { field: "tts_engine", equals: "alltalk" },
            },
            at_rvc_voice: {
                label: "AllTalk RVC Voice",
                type: "text",
                key: "voice.alltalk.rvc_voice",
                show_if: { field: "tts_engine", equals: "alltalk" },
            },
            at_rvc_pitch: {
                label: "AllTalk RVC Pitch",
                type: "text",
                key: "voice.alltalk.rvc_pitch",
                show_if: { field: "tts_engine", equals: "alltalk" },
            },
            // Piper
            piper_url: {
                label: "Piper URL",
                type: "text",
                key: "voice.piper.url",
                show_if: { field: "tts_engine", equals: "piper" },
            },
            // Coqui
            coqui_url: {
                label: "Coqui URL",
                type: "text",
                key: "voice.coqui_local.url",
                show_if: { field: "tts_engine", equals: "coqui-local" },
            },
            coqui_speaker: {
                label: "Coqui Speaker ID",
                type: "text",
                key: "voice.coqui_local.speaker_id",
                show_if: { field: "tts_engine", equals: "coqui-local" },
            },
            // Kokoro
            kokoro_url: {
                label: "Kokoro URL",
                type: "text",
                key: "voice.kokoro.url",
                show_if: { field: "tts_engine", equals: "kokoro" },
            },
            kokoro_voice: {
                label: "Kokoro Voice",
                type: "text",
                key: "voice.kokoro.voice",
                show_if: { field: "tts_engine", equals: "kokoro" },
            },
        }
    },
    "Character": {
        icon: "person",
        fields: {
            active_character: {
                label: "Active Character",
                type: "select",
                key: "character.active",
                options: ["default", "frieren", "custom"],
                description: "Which character personality to use",
            },
            companion_mode: {
                label: "Companion Mode",
                type: "toggle",
                key: "behavior.companion_enabled",
                description: "Enable proactive companion interactions",
            },
            thinking: {
                label: "Show Thinking",
                type: "toggle",
                key: "behavior.thinking_enabled",
                description: "Display reasoning before responses",
            },
            system_prompt: {
                label: "Additional Instructions",
                type: "textarea",
                key: "character.system_prompt",
                description: "Extra instructions appended to every conversation",
            },
        }
    },
    "Memory": {
        icon: "memory",
        fields: {
            memory_enabled: {
                label: "Memory Enabled",
                type: "toggle",
                key: "memory.enabled",
                description: "Allow Amalgam to remember context across sessions",
            },
            short_term_size: {
                label: "Context Window",
                type: "number",
                key: "memory.context_window",
                min: 5, max: 200,
                description: "Number of recent turns to keep in context",
            },
            long_term_enabled: {
                label: "Long-Term Memory",
                type: "toggle",
                key: "memory.fact_extraction",
                description: "Extract and persist important facts across sessions",
            },
        }
    },
    "Appearance": {
        icon: "palette",
        fields: {
            theme: {
                label: "Theme",
                type: "select",
                key: "ui.theme",
                options: ["dark", "midnight", "light", "nord"],
                description: "Color theme for the interface",
            },
            accent_color: {
                label: "Accent Color",
                type: "color",
                key: "ui.accent_color",
                description: "Primary accent color",
            },
            font_size: {
                label: "Font Size",
                type: "range",
                key: "ui.font_size",
                min: 10, max: 24,
                description: "Interface font size in pixels",
            },
            language: {
                label: "Language",
                type: "select",
                key: "ui.language",
                options: ["en", "zh"],
                description: "Interface language",
            },
        }
    },
    "Advanced": {
        icon: "tune",
        fields: {
            profile: {
                label: "Settings Profile",
                type: "select",
                key: "profile",
                options: ["default", "token-friendly", "quality", "custom"],
                description: "Profile for presets: token-friendly (lower token usage), quality (higher quality), custom (your tweaks)",
            },
            temperature: {
                label: "LLM Temperature",
                type: "range",
                key: "llm.temperature",
                min: 0, max: 2, step: 0.1,
                description: "Controls randomness in responses (0=deterministic, 2=creative)",
            },
            vault_path: {
                label: "Vault Path",
                type: "text",
                key: "vault.path",
                description: "Path to the RAG vault knowledge base",
            },
            vad_mode: {
                label: "VAD Mode",
                type: "select",
                key: "voice.vad_mode",
                options: ["0", "1", "2", "3"],
                description: "Voice Activity Detection aggressiveness",
            },
            log_level: {
                label: "Log Level",
                type: "select",
                key: "advanced.debug_log_level",
                options: ["DEBUG", "INFO", "WARNING", "ERROR"],
                description: "Verbosity of application logs",
            },
        }
    },
    "Privacy": {
        icon: "security",
        fields: {
            telemetry: {
                label: "Metrics Opt-Out",
                type: "toggle",
                key: "privacy.metrics_opt_out",
                description: "Opt out of anonymous usage metrics",
            },
            local_only: {
                label: "Local-Only Mode",
                type: "toggle",
                key: "privacy.local_only_mode",
                description: "Restrict all operations to local machine only",
            },
        }
    },
};

const PROVIDER_MODELS = {
    'gemini': ['gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-2.5-pro'],
    'openai': ['gpt-4o-mini', 'gpt-4o', 'gpt-4.1'],
    'anthropic': ['claude-sonnet-4-20250514', 'claude-haiku-3-5'],
    'groq': ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'deepseek-r1-distill-llama-70b'],
    'ollama': [],
    'openrouter': ['meta-llama/llama-3.1-8b-instruct:free'],
    'deepseek': ['deepseek-chat', 'deepseek-reasoner'],
    'siliconflow': ['deepseek-ai/DeepSeek-R1', 'deepseek-ai/DeepSeek-V3'],
    'zai': ['google/gemma-2-27b-it', 'Qwen/QwQ-32B-Preview'],
    'mistral': ['mistral-small-latest', 'mistral-large-latest'],
    'together': ['meta-llama/Llama-3.3-70B-Instruct-Turbo'],
    'chatgpt': ['gpt-4o-mini', 'gpt-4o'],
    'claude': ['claude-sonnet-4-20250514', 'claude-haiku-3-5'],
    'huggingface': [],
    'llamacpp': [],
    'koboldai': [],
    'aws': ['anthropic.claude-sonnet-4-20250514', 'anthropic.claude-3-5-sonnet-20241022', 'meta.llama3-70b-instruct-v1:0'],
    'gcp': ['gemini-2.0-flash-001', 'gemini-2.5-flash-001', 'gemini-2.5-pro-001'],
    'azure-openai': [],
    'alibaba': [],
};

let activeSettingsTab = 'Provider';
let _settingsCache = null;

function getSettings() { return _settingsCache; }

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _getNestedValue(obj, path) {
    if (!obj || !path) return undefined;
    // Try flat key first
    if (obj[path] !== undefined) return obj[path];
    // Try nested path
    const parts = path.split('.');
    let cur = obj;
    for (const p of parts) {
        if (cur === null || cur === undefined) return undefined;
        cur = cur[p];
    }
    return cur;
}

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
    // For dynamic model fields, also try without suffix
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
    return field.options || [];
}

function _shouldShowField(fieldId, field) {
    if (!field.show_if) return true;
    const settings = getSettings() || {};
    const sf = field.show_if;
    let currentVal;
    // Resolve the controlling field's value — prefer DOM over cached settings
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
        // Try to find the key in the schema
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

function renderSettings() {
    const container = document.getElementById('settings-body');
    if (!container) return;

    // Check if settings are loaded — show skeleton if not
    if (!_settingsCache) {
        container.innerHTML = `
            <div class="settings-sidebar">
                ${['Provider','Voice','Character','Memory','Appearance','Advanced','Privacy'].map(c => `
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
        <div class="settings-sidebar">
            ${sidebarHtml}
        </div>
        <div class="settings-content">
            ${searchHtml}
            <div id="settings-form-area">
                ${renderCategory(activeSettingsTab)}
            </div>
        </div>
    `;
}

function renderCategory(category) {
    const catData = SETTINGS_SCHEMA[category];
    if (!catData) return '<p class="settings-no-results">Unknown category</p>';

    const isProvider = category === 'Provider';
    const activeProv = isProvider ? (_getNestedValue(getSettings(), 'provider.active') || 'gemini') : null;

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

function renderField(fieldId, field) {
    const settings = getSettings() || {};
    const key = _getFieldKey(fieldId, field);
    let value = _getFieldValue(fieldId, field);
    const options = _getFieldOptions(fieldId, field);
    const desc = field.description ? `<span class="field-desc">${escapeHtml(field.description)}</span>` : '';

    // Common attributes for inputs/selects
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
            const opts = options.map(opt =>
                `<option value="${escapeHtml(opt)}" ${String(value) === opt ? 'selected' : ''}>${escapeHtml(opt)}</option>`
            ).join('');
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
                        <select ${commonAttrs}>
                            ${opts}
                        </select>
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
            // Add test-connection button for provider base_url fields
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
    }
}

function switchSettingsTab(category) {
    activeSettingsTab = category;
    renderSettings();
    _attachSettingsDelegates();
}

function filterSettings() {
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

function saveCategory(category) {
    const catData = SETTINGS_SCHEMA[category];
    if (!catData) return;

    const changed = {};
    for (const [fieldId, field] of Object.entries(catData.fields)) {
        if (!_shouldShowField(fieldId, field)) continue;
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

    // Also save active_provider for Provider category
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
            // Refresh settings cache
            fetch(`${BASE_URL}/api/settings`).then(r => r.json()).then(s => {
                _settingsCache = s;
            }).catch(() => {});
        } else {
            showToast(`Failed to save: ${data.error || 'unknown error'}`, 'danger');
        }
    })
    .catch(e => showToast(`Save failed: ${e.message}`, 'danger'));
}

function toggleFieldVisibility(id) {
    const inp = document.getElementById(id);
    if (!inp) return;
    const isPassword = inp.type === 'password';
    inp.type = isPassword ? 'text' : 'password';
    // Update the toggle button icon
    const btn = inp.parentElement?.querySelector('.toggle-vis-btn .material-icons-round');
    if (btn) btn.textContent = isPassword ? 'visibility_off' : 'visibility';
}

function testConnection(key) {
    // Extract provider name from key (e.g. "provider.gemini.api_key" -> "gemini")
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
                if (btn) {
                    btn.innerHTML = '<span class="material-icons-round" style="color:var(--success)">check_circle</span>';
                }
                showToast(`Connected (${result.latency_ms}ms)`, 'success');
            } else {
                if (btn) {
                    btn.innerHTML = '<span class="material-icons-round" style="color:var(--danger)">error</span>';
                }
                showToast(`Failed: ${result.error}`, 'danger');
            }
        })
        .catch(e => {
            if (btn) {
                btn.innerHTML = '<span class="material-icons-round" style="color:var(--danger)">error</span>';
            }
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

function fetchModels(provider) {
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
                // Find the model select and update its options
                const sel = document.getElementById('field-model');
                if (sel) {
                    const current = sel.value;
                    sel.innerHTML = '<option value="">Select model...</option>';
                    data.models.forEach(m => {
                        const o = document.createElement('option');
                        o.value = m;
                        o.textContent = m;
                        sel.appendChild(o);
                    });
                    if (current && data.models.includes(current)) sel.value = current;
                }
                showToast(`Found ${data.models.length} models`, 'success');
            } else {
                showToast('No models found', 'warning');
            }
        })
        .catch(e => showToast(`Failed to fetch models: ${e.message}`, 'danger'))
        .finally(() => {
            setTimeout(() => {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<span class="material-icons-round">cloud_sync</span>';
                }
            }, 3000);
        });
}

function _attachSettingsDelegates() {
    const body = document.getElementById('settings-body');
    if (!body) return;

    // Remove old listeners to avoid duplicates — use a flag
    if (body._delegatesAttached) return;
    body._delegatesAttached = true;

    // Handle changes for theme, language, font size, temperature, accent color
    body.addEventListener('change', (e) => {
        const el = e.target;
        const fieldId = el.dataset?.field || el.id?.replace('field-', '') || '';

        // Live-apply appearance changes
        if (fieldId === 'theme') {
            applyTheme(el.value);
        }
        if (fieldId === 'language') {
            const lang = el.value;
            if (typeof setLanguage === 'function') {
                setLanguage(lang);
            }
            fetch(`${BASE_URL}/api/settings/set`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'ui.language', value: lang })
            }).catch(() => {});
        }
        if (fieldId === 'accent_color') {
            applyAccentColor(el.value);
        }
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

        // Refresh category on engine/provider changes
        if (fieldId === 'stt_engine' || fieldId === 'tts_engine' || fieldId === 'active_provider') {
            // Re-render current category
            const area = document.getElementById('settings-form-area');
            if (area && !document.getElementById('settings-search-input')?.value) {
                area.innerHTML = renderCategory(activeSettingsTab);
                body._delegatesAttached = false;
                _attachSettingsDelegates();
            }
        }

        // Handle voice toggle sync with header toggles
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

    // Range input live updates
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

// Attach to window for onclick handlers
window.switchSettingsTab = switchSettingsTab;
window.filterSettings = filterSettings;
window.saveCategory = saveCategory;
window.toggleFieldVisibility = toggleFieldVisibility;
window.testConnection = testConnection;
window.fetchModels = fetchModels;

// Test connection from a field element (e.g. base_url text input)
window.testConnectionFromField = function(fieldId) {
    const inp = document.getElementById(fieldId);
    if (!inp) return;
    const key = inp.dataset.key || '';
    testConnection(key);
};

document.addEventListener('DOMContentLoaded', async () => {
    let savedLang = null;
    try {
        const r = await fetch(`${BASE_URL}/api/settings/get/ui.language`);
        if (r.ok) { const d = await r.json(); savedLang = d.value; }
    } catch {}
    await initI18n(savedLang);

    // Check if setup is needed (first-time setup wizard)
    try {
        const setupResp = await fetch(`${BASE_URL}/api/setup/status`);
        if (setupResp.ok) {
            const setupStatus = await setupResp.json();
            if (setupStatus.needs_setup) {
                showSetupWizard();
            }
        }
    } catch (e) {
        console.warn('Setup status check failed:', e);
    }

    initMetricsAutoRefresh();

    
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const statusDot = document.getElementById('status-dot');
    console.log('app:init - elements:', { chatMessages: !!chatMessages, chatInput: !!chatInput, sendBtn: !!sendBtn, statusDot: !!statusDot });
    if (!sendBtn) console.warn('app:init - send-btn not found in DOM');

    
    

    
    const avatarContainer = document.getElementById('avatar-canvas');
    const avatarPreview = document.getElementById('avatar-preview');
    let _avatarModule = null;
    let _vrmPath = BASE_URL + '/characters/default/model.vrm';
    let _mainAvatarCreated = false;

    import('./avatar.js').then(async (mod) => {
        const AvatarRenderer = mod.AvatarRenderer;
        const SpriteAvatar = mod.SpriteAvatar;
        const useSprite = window._gpuTier === 'low';
        _avatarModule = { AvatarRenderer, SpriteAvatar, useSprite };
        const settings = await fetch(BASE_URL + '/api/settings').then(r => r.json());
        _vrmPath = settings?.avatar?.model_path
            ? BASE_URL + `/${settings.avatar.model_path}`
            : BASE_URL + '/characters/default/model.vrm';

        
        if (avatarPreview) {
            avatarPreviewRenderer = new AvatarRenderer(avatarPreview, _vrmPath, { preview: true });
        }

        
        const observer = new IntersectionObserver((entries) => {
            if (entries[0].isIntersecting) {
                createMainAvatar();
                observer.disconnect();
            }
        }, { threshold: 0.1 });
        if (avatarContainer) observer.observe(avatarContainer);

    }).catch(err => {
        console.error('Avatar load failed:', err);
    });

    function createMainAvatar() {
        if (_mainAvatarCreated || !_avatarModule || !avatarContainer) return;
        _mainAvatarCreated = true;
        try {
            if (_avatarModule.useSprite) {
                avatarRenderer = new _avatarModule.SpriteAvatar(avatarContainer);
            } else {
                avatarRenderer = new _avatarModule.AvatarRenderer(avatarContainer, _vrmPath);
            }

            import('./speech-bubble.js').then(({ SpeechBubble }) => {
                speechBubble = new SpeechBubble(avatarContainer, avatarRenderer);
            }).catch(err => console.error('SpeechBubble load failed:', err));
            
            initIdleManager();
        } catch(err) {
            console.error('Main avatar creation failed:', err);
            const errDiv = document.createElement('div');
            errDiv.style.cssText = 'display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#e74c3c;font-size:0.8rem;gap:0.5rem;padding:1rem;text-align:center';
            const icon = document.createElement('span');
            icon.className = 'material-icons-round';
            icon.style.fontSize = '2rem';
            icon.textContent = 'error';
            const msg = document.createElement('span');
            msg.textContent = `Avatar error: ${err.message || err}`;
            errDiv.append(icon, msg);
            avatarContainer.replaceChildren(errDiv);
        }
    }

    
    function initIdleManager() {
        if (!avatarRenderer || avatarRenderer._idleManager || !_settingsCache) return;
        const idleCfg = _settingsCache.idle || {};
        avatarRenderer.initIdleManager({
            enabled: idleCfg.enabled !== false,
            timeBeforeIdleSec: idleCfg.time_before_idle_sec || 30,
            timeToSleepSec: idleCfg.time_to_sleep_sec || 120,
            minIntervalSec: idleCfg.min_interval_sec || 8,
            maxIntervalSec: idleCfg.max_interval_sec || 15,
            baseUrl: BASE_URL,
            onRequestIdlePrompt: () => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'idle_prompt_request' }));
                }
            },
            onSleep: () => {
                if (speechBubble) speechBubble.show('zzz...', 0);
            },
            onWake: () => {
                if (speechBubble) speechBubble.hide();
            },
        });
        
        avatarRenderer._idleManager.deactivate();
    }
    const statusText = document.getElementById('status-text');

    let ws = null;
    let currentAssistantMessage = null;
    let lastUserMessage = null;
    let voiceInputEnabled = false;
    let voiceOutputEnabled = false;
    let mcpServersCache = []; 

    
    let audioContext = null;
    let currentAudioSource = null;
    let isPlayingTTS = false;
    let ttsQueue = [];
    let ttsQueuePlaying = false;
    let ttsFlushRequested = false;
    let _speakingMsgId = null;

    
    let _streamBuffer = new Map();
    let _streamBufferTimer = null;
    function _flushStreamBuffer() {
        _streamBufferTimer = null;
        if (_streamBuffer.size === 0) return;
        for (const [el, newText] of _streamBuffer) {
            const accumulated = (el.dataset.rawText || '') + newText;
            el.dataset.rawText = accumulated;
            el.innerHTML = formatMessage(accumulated);
            // Add copy buttons to code blocks
            el.querySelectorAll('pre code').forEach(codeBlock => {
                if (!codeBlock.parentElement.querySelector('.copy-code-btn')) {
                    const btn = document.createElement('button');
                    btn.className = 'copy-code-btn';
                    btn.setAttribute('aria-label', 'Copy code');
                    btn.onclick = function() {
                        const t = this;
                        const c = t.previousElementSibling;
                        navigator.clipboard.writeText(c.textContent || c.innerText).then(() => {
                            t.classList.add('copied');
                            t.textContent = 'Copied';
                            setTimeout(() => {
                                t.classList.remove('copied');
                                t.textContent = '';
                            }, 2000);
                        });
                    };
                    codeBlock.parentElement.appendChild(btn);
                }
            });
        }
        for (const [el] of _streamBuffer) {
            if (!el.isConnected) {
                _streamBuffer.delete(el);
            }
        }
        _streamBuffer.clear();
    }
    function _appendStreamText(el, text) {
        const existing = _streamBuffer.get(el) || '';
        _streamBuffer.set(el, existing + text);
        if (!_streamBufferTimer) {
            _streamBufferTimer = requestAnimationFrame(_flushStreamBuffer);
        }
    }

    function ensureAudioContext() {
        if (!audioContext) {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (audioContext.state === 'suspended') {
            audioContext.resume();
        }
        return audioContext;
    }
    window.addEventListener('beforeunload', () => {
        if (audioContext && audioContext.state !== 'closed') {
            audioContext.close();
        }
    });

    function processTTSQueue() {
        if (ttsQueuePlaying || ttsQueue.length === 0) return;
        ttsQueuePlaying = true;
        
        ttsQueue.sort((a, b) => a.idx - b.idx);
        const item = ttsQueue.shift();
        playTTSAudio(item.audio, item.duration, item.visemeSchedule, () => {
            if (ttsFlushRequested) {
                ttsFlushRequested = false;
                ttsQueue = [];
                ttsQueuePlaying = false;
                isPlayingTTS = false;
                setStatus('ready');
                
                if (avatarRenderer?._idleManager) avatarRenderer._idleManager.deactivate();
                return;
            }
            ttsQueuePlaying = false;
            
            if (ttsQueue.length > 0) {
                processTTSQueue();
            } else {
                setStatus('ready');
            }
        });
    }

    function flushTTSQueue() {
        ttsFlushRequested = true;
        if (currentAudioSource) {
            try { currentAudioSource.stop(); } catch (_) {}
            currentAudioSource = null;
        }
    }

    
    function switchTab(tabId) {
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        const panel = document.getElementById(`tab-${tabId}`);
        if (panel) {
            document.querySelectorAll(`.nav-item[data-tab="${tabId}"]`).forEach(n => n.classList.add('active'));
            panel.classList.add('active');
            panel.focus({ preventScroll: true });
            localStorage.setItem('activeTab', tabId);
            if (tabId === 'settings') loadMCP();
            
            if (tabId === 'avatar') {
                createMainAvatar();
            }
            if (tabId === 'metrics') loadMetrics();
            if (tabId === 'swarm' && !window.swarmGraph) {
                if (typeof window.initSwarmTab === 'function') window.initSwarmTab();
            }
        }
    }

    
    const _hash = window.location.hash.replace('#', '').split('/');
    switchTab(localStorage.getItem('activeTab') || _hash[0] || 'chat');

    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            switchTab(item.dataset.tab);
            window.location.hash = item.dataset.tab;
        });
    });

    
    let _initComplete = false;
    let _settingsLoaded = false;
    window.addEventListener('hashchange', () => {
        const h = window.location.hash.replace('#', '').split('/');
        
        
        if (!_initComplete) return;
        const currentPanel = document.querySelector('.tab-panel.active');
        const currentTab = currentPanel ? currentPanel.id.replace('tab-', '') : null;
        if (h[0] && h[0] !== currentTab) {
            switchTab(h[0] || 'chat');
        }
    });

    
    let _reconnectAttempts = 0;
    const _reconnectDelays = [500, 1000, 2000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000];
    let _reconnectTimer = null;
    let _reconnectCountdownTimer = null;
    const _pendingMessages = [];

    // Heartbeat / ping-pong state (per-connection)
    let _pingInterval = null;
    let _pongPending = false;

    function _startHeartbeat(wsRef) {
        _stopHeartbeat();
        _pongPending = false;
        // Send a ping every 30 seconds
        _pingInterval = setInterval(() => {
            if (wsRef && wsRef.readyState === WebSocket.OPEN) {
                wsRef.send(JSON.stringify({ type: 'ping' }));
                _pongPending = true;
                // If we don't receive a pong within 10 seconds, assume stale
                setTimeout(() => {
                    if (_pongPending && wsRef && wsRef.readyState === WebSocket.OPEN) {
                        console.warn('Heartbeat: pong not received, closing stale connection');
                        wsRef.close(3000, 'Heartbeat timeout');
                        _pongPending = false;
                    }
                }, 10000);
            }
        }, 30000);
    }

    function _stopHeartbeat() {
        if (_pingInterval) {
            clearInterval(_pingInterval);
            _pingInterval = null;
        }
        _pongPending = false;
    }

    function _showReconnecting(attempt, delay) {
        statusDot.className = 'status-dot connecting';
        statusDot.setAttribute('aria-label', `Reconnecting attempt ${attempt}`);
        statusText.setAttribute('data-i18n', 'status.reconnecting');
        statusText.innerHTML = `<span class="reconnect-countdown">${t('status.reconnecting_countdown', { attempt: attempt, seconds: Math.round(delay / 1000) })}</span>`;
        // Show offline bar for extended disconnection
        const bar = document.getElementById('offline-bar');
        if (bar && attempt > 2) {
            bar.classList.remove('hidden');
            bar.classList.add('visible');
        }
        if (delay && delay > 0) {
            let remaining = Math.round(delay / 1000);
            if (_reconnectCountdownTimer) clearInterval(_reconnectCountdownTimer);
            _reconnectCountdownTimer = setInterval(() => {
                remaining--;
                if (remaining <= 0) {
                    clearInterval(_reconnectCountdownTimer);
                    _reconnectCountdownTimer = null;
                    statusText.setAttribute('data-i18n', 'status.reconnecting');
                    statusText.innerHTML = `<span class="reconnect-countdown">${t('status.reconnecting')}</span>`;
                } else {
                    statusText.setAttribute('data-i18n', 'status.reconnecting_countdown');
                    statusText.innerHTML = `<span class="reconnect-countdown">${t('status.reconnecting_countdown', { attempt: attempt, seconds: remaining })}</span>`;
                }
            }, 1000);
        }
    }

    function _clearReconnecting() {
        if (_reconnectCountdownTimer) {
            clearInterval(_reconnectCountdownTimer);
            _reconnectCountdownTimer = null;
        }
    }

    function connectWS() {
        if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
        _stopHeartbeat();
        ws = new WebSocket(`${WS_BASE}/ws/chat`);

        ws.onopen = () => {
            _reconnectAttempts = 0;
            _clearReconnecting();
            statusDot.className = 'status-dot online';
            statusText.innerHTML = t('status.connected');

            // Start heartbeat (ping every 30s)
            _startHeartbeat(ws);

            if (!_settingsLoaded) {
                api(BASE_URL + '/api/settings').then(s => { if (s) { applySettings(s); _settingsLoaded = true; }});
                loadCharacters();
                fetchCommands();
                loadSession('current');
            }
            loadHistory();
            [2000, 4000, 8000].forEach(delay => setTimeout(() => loadHistory(), delay));

            if (ws.readyState === WebSocket.OPEN) {
                // Send capabilities on connect (Capacitor native shell detection)
                ws.send(JSON.stringify({
                    type: 'client_hello',
                    capabilities: {
                        push_notifications: typeof Capacitor !== 'undefined' && !!Capacitor.Plugins?.PushNotifications,
                        native_microphone: typeof Capacitor !== 'undefined' && !!Capacitor.Plugins?.Microphone,
                        platform: typeof Capacitor !== 'undefined' ? 'capacitor' : 'web'
                    }
                }));
                if (voiceInputEnabled && isBrowserStt()) {
                    ws.send(JSON.stringify({ type: 'command', command: 'voice_input_on' }));
                } else if (!voiceInputEnabled && isBrowserStt()) {
                    ws.send(JSON.stringify({ type: 'command', command: 'voice_input_off' }));
                } else {
                    ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
                }
                ws.send(JSON.stringify({ type: 'command', command: voiceOutputEnabled ? 'voice_output_on' : 'voice_output_off' }));
            }

            while (_pendingMessages.length > 0) {
                const msg = _pendingMessages.shift();
                if (ws.readyState === WebSocket.OPEN) ws.send(msg);
            }
        };
        ws.onclose = (event) => {
            _stopHeartbeat();

            // Graceful closures (1000=normal, 1001=page navigate/refresh) —
            // reconnect silently without showing the full reconnection UI.
            if (event.code === 1000 || event.code === 1001) {
                _clearReconnecting();
                statusDot.className = 'status-dot connecting';
                statusText.innerHTML = t('status.reconnecting');
                _reconnectAttempts = 0;
                _reconnectTimer = setTimeout(connectWS, 200);
                return;
            }

            // Unexpected disconnection — show reconnect UI with backoff
            if (_reconnectAttempts >= _reconnectDelays.length) {
                _showReconnecting(_reconnectDelays.length, 5000);
                _reconnectTimer = setTimeout(connectWS, 5000);
                return;
            }
            const delay = _reconnectDelays[_reconnectAttempts];
            _showReconnecting(_reconnectAttempts + 1, delay);
            _reconnectAttempts++;
            _reconnectTimer = setTimeout(connectWS, delay);
        };
        ws.onerror = () => {
            console.warn('WebSocket error');
        };
        ws.onmessage = e => {
            try {
                const data = JSON.parse(e.data);

                // Heartbeat pong — just mark as received, no further processing
                if (data.type === 'pong') {
                    _pongPending = false;
                    return;
                }

                if (data.type === 'error') {
                    const severity = data.recoverable ? 'recoverable' : 'critical';
                    showToast(data.message || 'Unknown error', severity, {
                        service: data.service,
                        suggestion: data.suggestion,
                    });
                }
                handleWSMessage(data);
            } catch (err) {
                console.warn('WebSocket message parse error:', err);
            }
        };
    }

    

    
    const urlParams = new URLSearchParams(window.location.search);
    const IS_COMPANION = urlParams.get('mode') === 'companion';
    if (IS_COMPANION) {
        document.body.classList.add('companion-mode');
        
    }

    function handleWSMessage(data) {
        if (data.type === 'user_message_from_voice') {
            
            addMessage('user', data.text);
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'user_message', text: data.text }));
            }
            return;
        } else if (data.type === 'visibility') {
            const visible = data.visible;
            if (IS_TAURI && window.__TAURI__) {
                const { getCurrentWindow } = window.__TAURI__.window;
                const win = getCurrentWindow();
                if (visible) win.show();
                else win.hide();
            } else {
                
                const avatarView = document.getElementById('vrm-view');
                if (avatarView) avatarView.style.display = visible ? 'block' : 'none';
            }
            return;
        } else if (data.type === 'chat_start') {
            flushTTSQueue();
            currentAssistantMessage = addMessage('assistant', '');
            setStatus('thinking');
        } else if (data.type === 'chat_append') {
            if (data.role === 'assistant') {
                if (!currentAssistantMessage) {
                    currentAssistantMessage = addMessage('assistant', '');
                }
                if (data.error) {
                    currentAssistantMessage.classList.add('msg-error');
                }
                const body = currentAssistantMessage.querySelector('.msg-body');
                let cleanText = stripMarkers(data.text);
                _appendStreamText(body, cleanText);
                
                _speechBubbleAccumulator += cleanText;
                
                const pending = _streamBuffer.get(body);
                if (pending) {
                    const accumulated = (body.dataset.rawText || '') + pending;
                    body.dataset.rawText = accumulated;
                    body.innerHTML = formatMessage(accumulated);
                    _streamBuffer.delete(body);
                }
                
                if (data.finished && currentAssistantMessage?.classList.contains('msg-error')) {
                    _flushStreamBuffer();
                    currentAssistantMessage = null;
                    lastUserMessage = null;
                    setStatus('ready');
                    showToast('Message failed. You can click edit to retry.', 'danger');
                    return;
                }
                if (data.finished) {
                    _flushStreamBuffer();
                    
                    if (speechBubble && _speechBubbleAccumulator.trim()) {
                        speechBubble.show(_speechBubbleAccumulator.trim(), 6000);
                    }
                    _speechBubbleAccumulator = '';
                    currentAssistantMessage = null;
                    lastUserMessage = null;
                    if (!isPlayingTTS) {
                        setStatus('ready');
                        
                        if (avatarRenderer?._idleManager) avatarRenderer._idleManager.deactivate();
                    }
                }
            } else if (data.role === 'system') {
                if (data.session_id && data.session_id !== _currentSessionId) {
                    _currentSessionId = data.session_id;
                    location.hash = 'chat/' + data.session_id;
                    loadSession(data.session_id);
                    return;
                }
                addMessage('system', data.text);
            }
            chatMessages.scrollTop = chatMessages.scrollHeight;
        } else if (data.type === 'voice_state') {
            updateVoiceState(data.state);
        } else if (data.type === 'tts_audio') {
            
            ttsQueue.push({ audio: data.audio, duration: data.duration, idx: data.sentence_idx || 0, visemeSchedule: data.viseme_schedule || null });
            processTTSQueue();
        } else if (data.type === 'tts_error') {
            showToast(data.message || 'TTS failed', 'danger');
            setStatus('ready');
        } else if (data.type === 'emotion') {
            
            const emotion = (data.emotion || 'neutral').toLowerCase();
            if (avatarRenderer) avatarRenderer.setEmotion(emotion);
            if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion(emotion);
        } else if (data.type === 'expression') {
            
            const expr = (data.expression || 'neutral').toLowerCase();
            if (avatarRenderer) avatarRenderer.setExpression(expr);
            if (avatarPreviewRenderer) avatarPreviewRenderer.setExpression(expr);
        } else if (data.type === 'idle_prompt') {
            
            if (data.text) {
                if (speechBubble) speechBubble.show(data.text, 6000);
                if (avatarRenderer) avatarRenderer.setEmotion('relaxed');
                if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion('relaxed');
                setTimeout(() => {
                    if (avatarRenderer) avatarRenderer.setEmotion('neutral');
                    if (avatarPreviewRenderer) avatarPreviewRenderer.setEmotion('neutral');
                }, 6000);
            }
        } else if (data.type === 'animation') {
            
            if (data.url && avatarRenderer) {
                avatarRenderer.playAnimation(data.url);
            }
        } else if (data.type === 'roleplay') {
            
            if (data.animation_url && avatarRenderer) {
                avatarRenderer.playAnimation(data.animation_url);
            }
        } else if (data.type === 'typing') {
            setStatus('typing');
        } else if (data.type === 'stop_typing') {
            if (document.querySelector('#chat-avatar-status')?.textContent === 'Typing...') setStatus('ready');
        } else if (data.type === 'tool_call') {
            addMessage('tool', data.text || '');
        } else if (data.type === 'permission_request') {
            const overlay = document.getElementById('shell-permission-overlay');
            const cmdDisplay = document.getElementById('shell-pending-cmd');
            if (overlay && cmdDisplay) {
                cmdDisplay.textContent = data.command || '';
                overlay.style.display = 'flex';
            }
        } else if (data.type === 'thinking') {
            const thinkingEnabled = document.getElementById('thinking-toggle')?.checked ?? true;
            if (thinkingEnabled && data.text) {
                const body = currentAssistantMessage?.querySelector('.msg-body');
                if (body) {
                    const thinkEl = document.createElement('div');
                    thinkEl.className = 'thinking-bubble';
                    thinkEl.textContent = data.text;
                    body.appendChild(thinkEl);
                }
            }
        } else if (data.type === 'swarm_update') {
            if (typeof window.handleSwarmUpdate === 'function') {
                window.handleSwarmUpdate(data.data);
            }
        } else if (data.type === 'avatar_life_event') {
            if (data.event === 'bored' && avatarRenderer) {
                avatarRenderer.setEmotion('bored');
            }
        } else if (data.type === 'interrupt') {
            if (data.action === 'stop_audio_and_animation') {
                if (typeof flushTTSQueue === 'function') flushTTSQueue();
                if (avatarRenderer) avatarRenderer.setEmotion('surprised');
            }
        } else if (data.type === 'service_status') {
            if (data.services) updateHealthBar(data.services);
        } else if (data.type === 'tool_call_update') {
            if (data.tool_call_id) {
                updateToolCall(data.tool_call_id, data.status, data.result);
            }
        }
    }

    
    
    let _speechBubbleAccumulator = '';

    let _sessionHasMessages = false;
    let _currentSessionId = null;
    function updateSessionButtons() {
        document.getElementById('new-chat-btn').style.display = _sessionHasMessages ? '' : 'none';
        document.getElementById('new-session-btn').style.display = _sessionHasMessages ? '' : 'none';
    }

    
    function stripMarkers(text) {
        
        return (text || '')
            .replace(/\/\*\*[\s\S]*?(?:\*\*\/?|$)/g, '')
            .replace(/\/\*[\s\S]*?(?:\*\/|$)/g, '')
            .replace(/\/\[\[.*?\]\]/g, '')
            .replace(/\/\(\(.*?\)\)/g, '');
    }

    // ==================== Markdown & Message Formatting ====================

    let _toolCallIdCounter = 0;

    function renderMarkdown(text) {
        if (!text) return '';
        let html = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>');
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
        html = html.replace(/\n/g, '<br>');
        return html;
    }

    function formatMessage(text) {
        if (!text) return '';

        const toolCards = [];
        const thinkBlocks = [];

        // 1. Extract tool calls first — replace with placeholders
        let html = text.replace(
            /\[TOOL_CALL:\s*(\w+)\s*\(([^)]*)\)\]/g,
            (match, name, args) => {
                const id = 'tc-' + (++_toolCallIdCounter);
                const cardHtml = `
                        <div class="tool-call-card" data-tool="${name}" data-tool-call-id="${id}">
                            <div class="tool-call-header">
                                <span class="material-icons-round tool-call-icon">build</span>
                                <span class="tool-call-name">${escHtml(name)}</span>
                                <span class="tool-call-status" data-status="running">
                                    <span class="material-icons-round">sync</span>
                                    Running...
                                </span>
                            </div>
                            <div class="tool-call-args"><code>${escHtml(args.trim() || '')}</code></div>
                        </div>
                `;
                toolCards.push(cardHtml);
                return `%%TC${toolCards.length}%%`;
            }
        );

        // 2. Extract thinking blocks — replace with placeholders
        html = html.replace(
            /\[THINKING\]([\s\S]*?)\[\/THINKING\]/g,
            (match, content) => {
                const escapedContent = content.trim();
                const lines = escapedContent.split('\n').length;
                const summary = lines <= 3 ? escapedContent : escapedContent.split('\n').slice(0, 2).join('\n') + '...';
                const blockHtml = `
                    <details class="thinking-block" ${lines <= 3 ? 'open' : ''}>
                        <summary class="thinking-summary">
                            <span class="material-icons-round thinking-icon">psychology</span>
                            <span class="thinking-label">Thought <span class="thinking-lines">(${lines} lines)</span></span>
                            <span class="thinking-preview">${renderMarkdown(summary)}</span>
                        </summary>
                        <div class="thinking-content">${renderMarkdown(escapedContent)}</div>
                    </details>
                `;
                thinkBlocks.push(blockHtml);
                return `%%TB${thinkBlocks.length}%%`;
            }
        );

        // 3. Apply markdown to the remaining (placeholder-containing) text
        html = renderMarkdown(html);

        // 4. Replace placeholders with actual rendered HTML
        toolCards.forEach((card, i) => {
            html = html.replace(`%%TC${i + 1}%%`, () => card);
        });
        thinkBlocks.forEach((block, i) => {
            html = html.replace(`%%TB${i + 1}%%`, () => block);
        });

        return html;
    }

    function updateToolCall(toolId, status, result) {
        const card = document.querySelector(`.tool-call-card[data-tool-call-id="${toolId}"]`);
        if (!card) return;

        const statusEl = card.querySelector('.tool-call-status');
        const icons = {
            'running': ['sync', 'Running...'],
            'completed': ['check_circle', 'Completed'],
            'errored': ['error', 'Errored'],
            'retrying': ['refresh', 'Retrying...'],
        };
        const [icon, label] = icons[status] || ['help', status];

        statusEl.innerHTML = `<span class="material-icons-round">${icon}</span> ${label}`;
        statusEl.dataset.status = status;

        if (status === 'completed') {
            card.classList.add('tool-call-completed');
        } else if (status === 'errored') {
            card.classList.add('tool-call-errored');
            if (result) {
                const errorEl = document.createElement('div');
                errorEl.className = 'tool-call-error';
                errorEl.textContent = result;
                card.appendChild(errorEl);
            }
        }
    }

    function addToolCallRetry(card, toolName, args) {
        const retryBtn = document.createElement('button');
        retryBtn.className = 'tool-call-retry icon-btn';
        retryBtn.innerHTML = '<span class="material-icons-round">refresh</span> Retry';
        retryBtn.title = 'Retry this tool call';
        retryBtn.addEventListener('click', async () => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: 'retry_tool',
                    tool: toolName,
                    args: args,
                }));
            }
            retryBtn.disabled = true;
            retryBtn.innerHTML = '<span class="material-icons-round">sync</span> Retrying...';
        });
        card.appendChild(retryBtn);
    }

    function getMessageHtml(role, text) {
        let bodyHtml;
        if (role === 'assistant') {
            bodyHtml = formatMessage(text || '');
            // Wrap code blocks with copy button
            bodyHtml = bodyHtml.replace(
                /<pre><code(?:\s+class="[^"]*")?>([\s\S]*?)<\/code><\/pre>/g,
                '<pre><code>$1</code><button class="copy-code-btn" onclick="' +
                    'var t=this;var c=t.previousElementSibling;' +
                    'navigator.clipboard.writeText(c.textContent||c.innerText).then(function(){' +
                        't.classList.add(\'copied\');t.textContent=\'Copied\';' +
                        'setTimeout(function(){t.classList.remove(\'copied\');t.textContent=\'\';},2000);' +
                    '});" aria-label="Copy code"></button></pre>'
            );
        } else {
            const escaped = escHtml(text || '');
            bodyHtml = escaped;
        }
        return `<div class="msg-body">${bodyHtml}</div>` +
            `<div class="msg-actions">` +
                `<button class="msg-action" data-action="copy" title="Copy" aria-label="Copy message">` +
                    `<span class="material-icons-round">content_copy</span>` +
                `</button>` +
                `${role === 'user' ? `
                    <button class="msg-action" data-action="edit" title="Edit" aria-label="Edit message">
                        <span class="material-icons-round">edit</span>
                    </button>
                ` : ''}` +
                `${role === 'assistant' ? `
                    <button class="msg-action" data-action="regenerate" title="Regenerate" aria-label="Regenerate response">
                        <span class="material-icons-round">refresh</span>
                    </button>
                    <button class="msg-action" data-action="speak" title="Speak" aria-label="Speak message aloud">
                        <span class="material-icons-round">volume_up</span>
                    </button>
                ` : ''}` +
            `</div>`;
    }

    function updateSpeakButtons() {
        document.querySelectorAll('.msg-assistant .msg-action[data-action="speak"], .msg-assistant .msg-action[data-action="stop-speak"]').forEach(btn => {
            const msg = btn.closest('.msg');
            const isSpeaking = msg.dataset.msgId === _speakingMsgId;
            btn.dataset.action = isSpeaking ? 'stop-speak' : 'speak';
            btn.title = isSpeaking ? 'Stop' : 'Speak';
            btn.innerHTML = isSpeaking ? '<span class="material-icons-round">stop</span>' : '<span class="material-icons-round">volume_up</span>';
        });
    }

    function addMessage(role, text) {

        const welcome = chatMessages.querySelector('.welcome-message');
        if (welcome) welcome.remove();

        const div = document.createElement('div');
        div.className = `msg msg-${role}`;
        div.dataset.msgId = 'msg-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
        div.innerHTML = getMessageHtml(role, text);
        chatMessages.appendChild(div);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        if (!_sessionHasMessages) {
            _sessionHasMessages = true;
            updateSessionButtons();

            setTimeout(loadHistory, 1000);
        }

        // Collapsible long messages (>500px body)
        const body = div.querySelector('.msg-body');
        if (body && body.scrollHeight > 500) {
            div.classList.add('collapsible');
            const expandBtn = document.createElement('button');
            expandBtn.className = 'msg-expand-btn';
            expandBtn.textContent = 'Show more...';
            expandBtn.addEventListener('click', () => {
                const expanded = body.classList.toggle('expanded');
                expandBtn.textContent = expanded ? 'Show less' : 'Show more...';
            });
            div.appendChild(expandBtn);
        }

        return div;
    }

    function showWelcomeMessage() {
        const chatMessages = document.getElementById('chat-messages');
        if (!chatMessages) return;
        // Remove any existing content
        chatMessages.innerHTML = '';
        const welcome = document.createElement('div');
        welcome.className = 'welcome-message';
        welcome.setAttribute('role', 'status');
        welcome.innerHTML = `
            <div class="welcome-icon" aria-hidden="true">
                <span class="material-icons-round" style="font-size:3rem">forum</span>
            </div>
            <h2>${t('welcome.title')}</h2>
            <p>${t('welcome.subtitle')}</p>
            <div class="welcome-hints">
                <button class="welcome-hint" data-prompt="${t('welcome.hint_about')}">${t('welcome.hint_about')}</button>
                <button class="welcome-hint" data-prompt="${t('welcome.hint_capabilities')}">${t('welcome.hint_capabilities')}</button>
                <button class="welcome-hint" data-prompt="${t('welcome.hint_brainstorm')}">${t('welcome.hint_brainstorm')}</button>
            </div>
        `;
        chatMessages.appendChild(welcome);

        // Handle welcome hint clicks
        welcome.querySelectorAll('.welcome-hint').forEach(btn => {
            btn.addEventListener('click', () => {
                const prompt = btn.dataset.prompt;
                if (prompt && ws?.readyState === WebSocket.OPEN) {
                    addMessage('user', prompt);
                    ws.send(JSON.stringify({ type: 'user_message', text: prompt }));
                    chatInput.value = '';
                    setStatus('thinking');
                }
            });
        });
    }

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
            chatInput.dataset.editTarget = msg.dataset.msgId || '';
            chatInput.focus();
        } else if (action === 'regenerate') {
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
        } else if (action === 'speak' || action === 'stop-speak') {
            if (_speakingMsgId === msg.dataset.msgId && action === 'stop-speak') {
                flushTTSQueue();
                _speakingMsgId = null;
                updateSpeakButtons();
            } else if (ws?.readyState === WebSocket.OPEN) {
                if (isPlayingTTS) flushTTSQueue();
                _speakingMsgId = msg.dataset.msgId;
                updateSpeakButtons();
                ws.send(JSON.stringify({ type: 'command', command: 'speak', text: body }));
            }
        }
    });

    function clearErrors() {
        chatMessages.querySelectorAll('.msg-assistant.msg-error').forEach(el => {
            const prev = el.previousElementSibling;
            if (prev?.classList.contains('msg-user')) prev.remove();
            el.remove();
        });
    }

    let _sending = false;
    function sendMessage() {
        if (_sending) { console.log('sendMessage: already sending, ignored'); return; }
        _sending = true;
        console.log('sendMessage called');
        const text = chatInput.value.trim();
        console.log('Text:', text);
        if (!text) { _sending = false; return; }
        if (!ws) { _sending = false; console.warn('send: ws null'); showToast('Not connected', 'danger'); return; }
        if (ws.readyState === WebSocket.CONNECTING) { _sending = false; console.warn('send: ws connecting'); showToast('Connecting...', 'danger'); return; }
        if (ws.readyState !== WebSocket.OPEN) {
            _pendingMessages.push(JSON.stringify({ type: 'user_message', text }));
            chatInput.value = '';
            chatInput.style.height = 'auto';
            _sending = false;
            showToast('Message queued — reconnecting...', 'warning');
            return;
        }

        
        if (text.startsWith('/')) {
            const parts = text.split(/\s+/);
            const command = parts[0].substring(1).toLowerCase();
            const args = parts.slice(1).join(' ');
            ws.send(JSON.stringify({ type: 'slash_command', command, args }));
            chatInput.value = '';
            chatInput.style.height = 'auto';
            _sending = false;
            return;
        }

        clearErrors();
        flushTTSQueue();
        if (typeof avatarRenderer?.interact === 'function') avatarRenderer.interact();

        
        const editId = chatInput.dataset.editTarget;
        if (editId) {
            const oldMsg = chatMessages.querySelector(`[data-msg-id="${editId}"]`);
            if (oldMsg) {
                const next = oldMsg.nextElementSibling;
                if (next?.classList.contains('msg-assistant')) next.remove();
                oldMsg.remove();
            }
            delete chatInput.dataset.editTarget;
        }

        clearTimeout(_typingTimer);
        setStatus('ready');
        try { 
            console.log('Sending stop_typing command');
            ws.send(JSON.stringify({ type: 'command', command: 'stop_typing' })); 
        } catch (e) { 
            console.warn('send stop_typing:', e); 
        }
        console.log('Adding user message:', text);
        lastUserMessage = addMessage('user', text);
        const msg = { type: 'user_message', text };
        if (_pendingImageData) {
            msg.images = [_pendingImageData];
            _pendingImageData = null;
            if (imgPreview) imgPreview.style.display = 'none';
            if (imgPreviewSrc) imgPreviewSrc.src = '';
            if (imgInput) imgInput.value = '';
        }
        try {
            console.log('Sending user_message:', JSON.stringify(msg));
            ws.send(JSON.stringify(msg));
        } catch (e) {
            console.warn('send user_message:', e); showToast('Send failed', 'danger');
        }
        
        if (avatarRenderer?._idleManager) avatarRenderer._idleManager.wake();
        chatInput.value = '';
        chatInput.style.height = 'auto';
        _sending = false;
    }

    if (sendBtn) {
        sendBtn.addEventListener('click', sendMessage);
    }

    
    let _pendingImageData = null;
    const imgBtn = document.getElementById('img-btn');
    const imgInput = document.getElementById('img-input');
    const imgPreview = document.getElementById('img-preview');
    const imgPreviewSrc = document.getElementById('img-preview-src');
    const imgPreviewRemove = document.getElementById('img-preview-remove');
    if (imgBtn && imgInput) {
        imgBtn.addEventListener('click', () => imgInput.click());
        imgInput.addEventListener('change', (e) => {
            const files = e.target.files;
            console.log('Image input change:', files?.length, 'files');
            const file = files?.[0];
            if (!file) { console.log('No file selected'); return; }
            console.log('Reading file:', file.name, file.size, file.type);
            const reader = new FileReader();
            reader.onload = (ev) => {
                console.log('FileReader loaded, result length:', ev.target?.result?.length);
                _pendingImageData = ev.target?.result;
                if (imgPreviewSrc && imgPreview) {
                    imgPreviewSrc.src = _pendingImageData;
                    imgPreview.style.display = 'flex';
                    console.log('Preview shown');
                }
            };
            reader.onerror = (err) => console.error('FileReader error:', err);
            reader.readAsDataURL(file);
        });
    }
    if (imgPreviewRemove) {
        imgPreviewRemove.addEventListener('click', () => {
            _pendingImageData = null;
            if (imgInput) imgInput.value = '';
            if (imgPreview) imgPreview.style.display = 'none';
            if (imgPreviewSrc) imgPreviewSrc.src = '';
        });
    }

    document.addEventListener('keydown', e => {
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
            const tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'BUTTON') return;
            const activeTab = document.querySelector('.tab-panel.active');
            if (!activeTab) return;
            const target = activeTab.id === 'tab-chat' ? chatInput : activeTab.id === 'tab-characters' ? document.getElementById('char-search-input') : null;
            if (target) {
                target.focus();
                requestAnimationFrame(() => target.setSelectionRange(target.value.length, target.value.length));
            }
        }
    });

    
    if (IS_TAURI) {
        document.addEventListener('keydown', e => {
            if (e.ctrlKey && e.key === 'r') {
                e.preventDefault();
                if (e.shiftKey) {
                    
                    window.location.href = window.location.pathname + '?_=' + Date.now();
                } else {
                    window.location.reload();
                }
            }
        });
    }

    let CMD_LIST = [];
    const cmdSuggestions = document.getElementById('cmd-suggestions');
    let _cmdSelectedIndex = -1;

    function updateCmdSuggestions() {
        const val = chatInput.value;
        if (!val.startsWith('/')) { cmdSuggestions.classList.remove('show'); return; }
        const partial = val.substring(1).toLowerCase();
        const matches = CMD_LIST.filter(c => c.name.startsWith(partial));
        if (!matches.length || partial.includes(' ')) { cmdSuggestions.classList.remove('show'); return; }
        cmdSuggestions.innerHTML = matches.map((c, i) =>
            `<div class="cmd-item${i === _cmdSelectedIndex ? ' selected' : ''}" data-index="${i}">
                <span class="cmd-name">/${escHtml(c.name)}</span>
                <span class="cmd-desc">${escHtml(c.desc)}</span>
            </div>`
        ).join('');
        cmdSuggestions.classList.add('show');
        _cmdSelectedIndex = Math.min(_cmdSelectedIndex, matches.length - 1);
    }

    chatInput.addEventListener('keydown', e => {
        if (cmdSuggestions.classList.contains('show')) {
            const items = cmdSuggestions.querySelectorAll('.cmd-item');
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                _cmdSelectedIndex = Math.min(_cmdSelectedIndex + 1, items.length - 1);
                items.forEach((el, i) => el.classList.toggle('selected', i === _cmdSelectedIndex));
                return;
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                _cmdSelectedIndex = Math.max(_cmdSelectedIndex - 1, 0);
                items.forEach((el, i) => el.classList.toggle('selected', i === _cmdSelectedIndex));
                return;
            }
            if (e.key === 'Enter' || e.key === 'Tab') {
                if (_cmdSelectedIndex >= 0 && _cmdSelectedIndex < items.length) {
                    e.preventDefault();
                    const name = items[_cmdSelectedIndex].querySelector('.cmd-name')?.textContent || '';
                    chatInput.value = name + ' ';
                    chatInput.style.height = 'auto';
                    chatInput.style.height = chatInput.scrollHeight + 'px';
                    cmdSuggestions.classList.remove('show');
                    chatInput.focus();
                    return;
                }
            }
            if (e.key === 'Escape') {
                cmdSuggestions.classList.remove('show');
                return;
            }
        }
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    chatInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = this.scrollHeight + 'px';
        _cmdSelectedIndex = 0;
        updateCmdSuggestions();
    });
    chatInput.addEventListener('blur', () => {
        setTimeout(() => cmdSuggestions.classList.remove('show'), 150);
    });
    chatInput.addEventListener('focus', updateCmdSuggestions);
    let _typingTimer;
    chatInput.addEventListener('keydown', () => {
        clearTimeout(_typingTimer);
        setStatus('typing');
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'command', command: 'typing' }));
        _typingTimer = setTimeout(() => {
            setStatus('ready');
            if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'command', command: 'stop_typing' }));
        }, 2000);
    });

    function escHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    
    function setStatus(state) {
        const el = document.getElementById('chat-avatar-status');
        const avatar = document.getElementById('chat-avatar');
        if (!el || !avatar) return;
        avatar.className = 'chat-avatar';
        const labels = {
            thinking: 'status.thinking',
            speaking: 'status.speaking',
            listening: 'status.listening',
            typing: 'status.typing',
            error: 'status.error',
        };
        el.textContent = t(labels[state] || 'status.ready');
        if (state && labels[state]) {
            avatar.classList.add(state);
        }
    }

    function setCharacterAvatar(charName) {
        document.getElementById('chat-avatar-name').textContent = charName;
    }

    
    let browserSpeechRec = null;
    let browserSpeechRestartTimer = null;

    function isBrowserStt() {
        const el = document.getElementById('stt-engine');
        if (el) return el.value === 'browser';
        // Fallback to cached settings
        return (_getNestedValue(getSettings(), 'voice.stt_engine') || 'browser') === 'browser';
    }

    function startBrowserSpeechRec() {
        if (browserSpeechRec) return;
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            showToast('Speech Recognition not supported in this browser. Try Chrome.', 'danger');
            return;
        }
        browserSpeechRec = new SpeechRecognition();
        browserSpeechRec.continuous = true;
        browserSpeechRec.interimResults = true;
        browserSpeechRec.lang = 'en-US';

        browserSpeechRec.onresult = (event) => {
            let finalText = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                if (event.results[i].isFinal) {
                    finalText += event.results[i][0].transcript;
                }
            }
            if (finalText.trim() && ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'user_message', text: finalText.trim() }));
            }
        };

        browserSpeechRec.onerror = (event) => {
            console.warn('Browser SpeechRecognition error:', event.error);
            if (event.error === 'not-allowed') {
                showToast('Microphone access denied. Check browser permissions.', 'danger');
                stopBrowserSpeechRec();
            } else if (event.error === 'aborted') {
                
            } else if (event.error === 'no-speech') {
                
            } else {
                showToast(`Speech recognition error: ${event.error}`, 'danger');
            }
        };

        browserSpeechRec.onend = () => {
            
            if (voiceInputEnabled && isBrowserStt()) {
                browserSpeechRestartTimer = setTimeout(() => {
                    if (voiceInputEnabled && isBrowserStt()) {
                        try { browserSpeechRec?.start(); } catch (_) {}
                    }
                }, 300);
            }
        };

        try {
            browserSpeechRec.start();
        } catch (e) {
            console.warn('Browser SpeechRecognition start failed:', e);
        }
    }

    function stopBrowserSpeechRec() {
        if (browserSpeechRestartTimer) {
            clearTimeout(browserSpeechRestartTimer);
            browserSpeechRestartTimer = null;
        }
        if (browserSpeechRec) {
            try { browserSpeechRec.stop(); } catch (_) {}
            browserSpeechRec = null;
        }
    }

    
    const voiceInputToggle = document.getElementById('voice-input-toggle');
    const voiceOutputToggle = document.getElementById('voice-output-toggle');
    const voiceInputToggleSettings = document.getElementById('voice-input-toggle-settings');
    const voiceOutputToggleSettings = document.getElementById('voice-output-toggle-settings');

    function toggleVoiceInput() {
        voiceInputEnabled = !voiceInputEnabled;
        voiceInputToggle.querySelector('.material-icons-round').textContent = voiceInputEnabled ? 'mic' : 'mic_off';
        voiceInputToggle.classList.toggle('active', voiceInputEnabled);
        if (voiceInputToggleSettings) {
            voiceInputToggleSettings.checked = voiceInputEnabled;
        }
        if (voiceInputEnabled && isBrowserStt()) {
            startBrowserSpeechRec();
            
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'command', command: 'voice_input_on' }));
            }
        } else {
            if (isBrowserStt()) {
                stopBrowserSpeechRec();
                
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'command', command: 'voice_input_off' }));
                }
            } else {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
                }
            }
        }
        fetch(BASE_URL + '/api/settings/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: 'ui.voice_input', value: voiceInputEnabled })
        });
        showToast(voiceInputEnabled ? 'Voice input on' : 'Voice input off');
    }

    voiceInputToggle.addEventListener('click', toggleVoiceInput);

    voiceOutputToggle.addEventListener('click', () => {
        voiceOutputEnabled = !voiceOutputEnabled;
        voiceOutputToggle.querySelector('.material-icons-round').textContent = voiceOutputEnabled ? 'volume_up' : 'volume_off';
        voiceOutputToggle.classList.toggle('active', voiceOutputEnabled);
        if (voiceOutputToggleSettings) {
            voiceOutputToggleSettings.checked = voiceOutputEnabled;
        }
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'command', command: voiceOutputEnabled ? 'voice_output_on' : 'voice_output_off' }));
        }
        showToast(voiceOutputEnabled ? 'Voice output on' : 'Voice output off');
    });

    if (voiceInputToggleSettings) {
        voiceInputToggleSettings.addEventListener('change', () => {
            voiceInputEnabled = voiceInputToggleSettings.checked;
            voiceInputToggle.querySelector('.material-icons-round').textContent = voiceInputEnabled ? 'mic' : 'mic_off';
            voiceInputToggle.classList.toggle('active', voiceInputEnabled);
            if (voiceInputEnabled && isBrowserStt()) {
                startBrowserSpeechRec();
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'command', command: 'voice_input_on' }));
                }
            } else {
                if (isBrowserStt()) {
                    stopBrowserSpeechRec();
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({ type: 'command', command: 'voice_input_off' }));
                    }
                } else {
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
                    }
                }
            }
            showToast(voiceInputEnabled ? 'Voice input on' : 'Voice input off');
        });
    }

    if (voiceOutputToggleSettings) {
        voiceOutputToggleSettings.addEventListener('change', () => {
            voiceOutputEnabled = voiceOutputToggleSettings.checked;
            voiceOutputToggle.querySelector('.material-icons-round').textContent = voiceOutputEnabled ? 'volume_up' : 'volume_off';
            voiceOutputToggle.classList.toggle('active', voiceOutputEnabled);
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'command', command: voiceOutputEnabled ? 'voice_output_on' : 'voice_output_off' }));
            }
            fetch(BASE_URL + '/api/settings/set', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: 'ui.voice_output', value: voiceOutputEnabled })
            });
            showToast(voiceOutputEnabled ? 'Voice output on' : 'Voice output off');
        });
    }

    function updateVoiceState(state) {
        const bars = document.getElementById('voice-bars');
        bars.className = 'voice-bars';
        if (state === 'recording' || state === 'speaking') {
            bars.classList.add('active');
        }
        if (state === 'recording') setStatus('listening');
        else if (state === 'speaking') setStatus('speaking');
        else setStatus('ready');
    }

    async function playTTSAudio(base64Wav, duration, visemeSchedule, onComplete) {
        try {
            const ctx = ensureAudioContext();

            
            let binaryStr;
            try {
                binaryStr = atob(base64Wav);
            } catch (e) {
                console.warn('TTS: malformed base64, skipping');
                if (typeof onComplete === 'function') onComplete();
                return;
            }
            const bytes = new Uint8Array(binaryStr.length);
            for (let i = 0; i < binaryStr.length; i++) {
                bytes[i] = binaryStr.charCodeAt(i);
            }

            let audioBuffer;
            try {
                audioBuffer = await ctx.decodeAudioData(bytes.buffer);
            } catch (e) {
                console.warn('TTS: malformed audio data, skipping');
                if (typeof onComplete === 'function') onComplete();
                return;
            }

            const source = ctx.createBufferSource();
            source.buffer = audioBuffer;

            
            const analyser = ctx.createAnalyser();
            analyser.fftSize = 2048;
            source.connect(analyser);
            source.connect(ctx.destination);
            currentAudioSource = source;
            isPlayingTTS = true;
            updateSpeakButtons();

            
            if (avatarRenderer?._idleManager) avatarRenderer._idleManager.activate();

            setStatus('speaking');

            
            if (avatarRenderer) avatarRenderer.startLipSync(ctx, analyser, visemeSchedule);
            if (avatarPreviewRenderer) avatarPreviewRenderer.startLipSync(ctx, analyser, visemeSchedule);

            source.onended = () => {
                isPlayingTTS = false;
                currentAudioSource = null;
                _speakingMsgId = null;
                updateSpeakButtons();
                if (avatarRenderer) avatarRenderer.stopLipSync();
                if (avatarPreviewRenderer) avatarPreviewRenderer.stopLipSync();
                
                if (avatarRenderer?._idleManager) avatarRenderer._idleManager.deactivate();
                if (onComplete) onComplete();
            };

            source.start(0);
        } catch (err) {
            console.error('TTS playback error:', err);
            isPlayingTTS = false;
            currentAudioSource = null;
            if (avatarRenderer) avatarRenderer.setMouthOpen(0);
            if (onComplete) onComplete();
        }
    }

    
    async function api(url, opts = {}) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), opts.timeout || 30000);
        try {
            const r = await fetch(url, { ...opts, signal: controller.signal });
            clearTimeout(timeout);
            return await r.json();
        } catch (e) {
            clearTimeout(timeout);
            console.error(`API error (${url}):`, e);
            return null;
        }
    }

    function showToast(message, type = 'system', options = {}) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        // Icon based on type
        const icons = {
            'success': 'check_circle',
            'danger': 'error',
            'critical': 'error',
            'warning': 'warning',
            'recoverable': 'warning',
            'system': 'info',
            'info': 'info',
        };
        const icon = icons[type] || 'info';
        
        // Structured content
        const service = options.service ? `<span class="toast-service">${options.service}</span>` : '';
        const suggestion = options.suggestion ? `<span class="toast-suggestion">${options.suggestion}</span>` : '';
        const dismissBtn = type === 'critical' || type === 'danger' 
            ? '<button class="toast-dismiss" onclick="this.parentElement.remove()"><span class="material-icons-round">close</span></button>' 
            : '';
        
        toast.innerHTML = `
            <span class="material-icons-round toast-icon">${icon}</span>
            <div class="toast-content">
                ${service}
                <span class="toast-message">${message}</span>
                ${suggestion}
            </div>
            ${dismissBtn}
        `;
        
        container.appendChild(toast);
        
        // Auto-dismiss for non-critical types
        const autoDismiss = {
            'success': 3000,
            'system': 3000,
            'info': 3000,
            'warning': 5000,
            'recoverable': 8000,
        };
        
        const duration = autoDismiss[type];
        if (duration) {
            setTimeout(() => {
                toast.style.animation = 'toast-out 0.3s ease forwards';
                setTimeout(() => toast.remove(), 300);
            }, duration);
        }
    }

    
    async function fetchCommands() {
        try {
            const data = await api(BASE_URL + '/api/commands');
            CMD_LIST = data?.commands || [];
        } catch { CMD_LIST = []; }
    }

    async function loadSession(sessionId) {
        const chatMessages = document.getElementById('chat-messages');
        chatMessages.innerHTML = '<div class="msg msg-system" style="text-align:center;color:var(--muted);padding:2rem"><span class="material-icons-round" style="font-size:1.5rem;display:block;margin-bottom:0.5rem">hourglass_top</span>Loading conversation...</div>';
        _sessionHasMessages = false;
        updateSessionButtons();
        try {
            const session = await api(BASE_URL + `/api/memory/session/${sessionId}`);
            chatMessages.innerHTML = '';
            function _setHash(sid) {
                const tab = document.querySelector('.tab-panel.active');
                if (!tab || tab.id === 'tab-chat') {
                    location.hash = 'chat/' + sid;
                }
            }
            if (session?.exists === false) {
                const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
                if (res?.session_id) {
                    _currentSessionId = res.session_id;
                    _setHash(res.session_id);
                }
                return;
            }
            if (session?.messages?.length) {
                _sessionHasMessages = true;
                session.messages.forEach((m, i) => {
                    let role = m.role;
                    const content = stripMarkers(m.content);
                    if (role === 'system' && (content.startsWith('Tool result') || content.startsWith('Tool parse error'))) {
                        role = 'tool';
                    }
                    const div = document.createElement('div');
                    div.className = `msg msg-${role}`;
                    div.dataset.msgId = `msg-loaded-${i}`;
                    if (role === 'assistant' && isErrorText(content)) {
                        div.classList.add('msg-error');
                    }
                    div.innerHTML = getMessageHtml(role, content);
                    chatMessages.appendChild(div);
                });
                chatMessages.scrollTop = chatMessages.scrollHeight;
            } else {
                // Show welcome / empty state
                _sessionHasMessages = false;
                updateSessionButtons();
                showWelcomeMessage();
            }
            _currentSessionId = session?.session_id || sessionId;
            if (_currentSessionId) _setHash(_currentSessionId);
            updateSessionButtons();
        } catch (e) {
            chatMessages.innerHTML = '';
            const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
            _currentSessionId = res?.session_id || sessionId;
            if (res?.session_id) _setHash(res.session_id);
            updateSessionButtons();
        }
    }

    window.addEventListener('hashchange', () => {
        const parts = location.hash.replace('#', '').split('/');
        if (parts[0] === 'chat' && parts[1] && parts[1] !== _currentSessionId) {
            loadSession(parts[1]);
        }
    });

    function setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ctrl+Enter or Cmd+Enter to send
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                const sendBtn = document.getElementById('send-btn');
                if (sendBtn && !sendBtn.disabled) {
                    e.preventDefault();
                    sendBtn.click();
                }
                return;
            }
            // Escape to close modals
            if (e.key === 'Escape') {
                const historyPanel = document.getElementById('history-panel');
                if (historyPanel?.classList.contains('visible')) {
                    historyPanel.classList.remove('visible');
                    return;
                }
                const kbdHint = document.getElementById('kbd-hint');
                if (kbdHint?.classList.contains('visible')) {
                    kbdHint.classList.remove('visible');
                    return;
                }
                // Close shell permission overlay
                const shellOverlay = document.getElementById('shell-permission-overlay');
                if (shellOverlay && shellOverlay.style.display !== 'none') {
                    shellOverlay.style.display = 'none';
                    return;
                }
                // Close setup wizard overlay
                const setupWizard = document.getElementById('setup-wizard-overlay');
                if (setupWizard && setupWizard.style.display !== 'none') {
                    setupWizard.style.display = 'none';
                    if (setupWizard._trapFocusHandler) {
                        setupWizard.removeEventListener('keydown', setupWizard._trapFocusHandler);
                        delete setupWizard._trapFocusHandler;
                    }
                    return;
                }
                return;
            }
            // / to focus chat input
            if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
                const chatInput = document.getElementById('chat-input');
                if (chatInput && document.activeElement !== chatInput) {
                    const activeTag = document.activeElement?.tagName?.toLowerCase();
                    if (activeTag !== 'input' && activeTag !== 'textarea' && activeTag !== 'select') {
                        e.preventDefault();
                        chatInput.focus();
                    }
                }
            }
            // ? to show keyboard shortcuts hint
            // Commented out: #kbd-hint element doesn't exist in the DOM
            // if (e.key === '?' && !e.ctrlKey && !e.metaKey && !e.altKey && e.shiftKey) {
            //     const kbdHint = document.getElementById('kbd-hint');
            //     if (kbdHint) {
            //         kbdHint.classList.toggle('visible');
            //     }
            // }
        });
    }

    async function init() {
        const settings = await api(BASE_URL + '/api/settings');
        if (settings) { await applySettings(settings); _settingsLoaded = true; }
        await loadCharacters();
        await fetchCommands();
        setupKeyboardShortcuts();


        const parts = location.hash.replace('#', '').split('/');
        const sessionId = parts[0] === 'chat' && parts[1] ? parts[1] : null;
        await loadSession(sessionId || 'current');

        loadHistory();

        [2000, 4000, 8000].forEach(delay => setTimeout(() => loadHistory(), delay));

        _initComplete = true;
    }

    function applyTheme(theme) {
        if (theme === 'dark') {
            document.documentElement.removeAttribute('data-theme');
        } else {
            document.documentElement.setAttribute('data-theme', theme);
        }
    }

    function applyAccentColor(hex) {
        document.documentElement.style.setProperty('--accent', hex);
        
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        document.documentElement.style.setProperty('--accent-dim', `rgba(${r}, ${g}, ${b}, 0.15)`);
        
        document.querySelectorAll('#color-swatches .swatch').forEach(s => {
            s.classList.toggle('active', s.dataset.color === hex);
        });
        document.getElementById('accent-color-picker').value = hex;
    }

    
    document.querySelectorAll('#color-swatches .swatch').forEach(swatch => {
        swatch.addEventListener('click', () => {
            applyAccentColor(swatch.dataset.color);
        });
    });
    document.getElementById('accent-color-picker').addEventListener('input', e => {
        applyAccentColor(e.target.value);
    });

    async function applySettings(d) {
        _settingsCache = d;

        initIdleManager();

        // Voice I/O state (synced with header toggles)
        voiceInputEnabled = d.ui?.voice_input ?? true;
        voiceOutputEnabled = d.ui?.voice_output ?? true;
        voiceInputToggle.querySelector('.material-icons-round').textContent = voiceInputEnabled ? 'mic' : 'mic_off';
        voiceInputToggle.classList.toggle('active', voiceInputEnabled);
        voiceOutputToggle.querySelector('.material-icons-round').textContent = voiceOutputEnabled ? 'volume_up' : 'volume_off';
        voiceOutputToggle.classList.toggle('active', voiceOutputEnabled);
        if (voiceInputToggleSettings) voiceInputToggleSettings.checked = voiceInputEnabled;
        if (voiceOutputToggleSettings) voiceOutputToggleSettings.checked = voiceOutputEnabled;
        
        if (ws && ws.readyState === WebSocket.OPEN) {
            if (voiceInputEnabled && isBrowserStt()) {
                ws.send(JSON.stringify({ type: 'command', command: 'voice_input_on' }));
            } else if (!voiceInputEnabled && isBrowserStt()) {
                ws.send(JSON.stringify({ type: 'command', command: 'voice_input_off' }));
            } else {
                ws.send(JSON.stringify({ type: 'command', command: voiceInputEnabled ? 'voice_input_on' : 'voice_input_off' }));
            }
            ws.send(JSON.stringify({ type: 'command', command: voiceOutputEnabled ? 'voice_output_on' : 'voice_output_off' }));
        }
        
        if (voiceInputEnabled && isBrowserStt()) {
            startBrowserSpeechRec();
        } else if (isBrowserStt()) {
            stopBrowserSpeechRec();
        }

        
        // Thinking toggle (header element)
        const thinkingToggle = document.getElementById('thinking-toggle');
        if (thinkingToggle) {
            const thinkingEnabled = d.ui?.thinking_enabled ?? true;
            thinkingToggle.checked = thinkingEnabled;
            thinkingToggle.onchange = async function() {
                await fetch(BASE_URL + '/api/settings/set', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ key: 'ui.thinking_enabled', value: this.checked })
                });
            };
        }

        // Theme (affects the whole page)
        const theme = d.ui?.theme || 'dark';
        applyTheme(theme);
        const fs = d.ui?.font_size || 14;
        document.documentElement.style.setProperty('--font-size', fs + 'px');

        // Character avatar
        const charId = d.character?.active || 'amalgam';
        
        const chars = await api(BASE_URL + '/api/characters');
        const charName = chars?.[charId]?.name || (charId.charAt(0).toUpperCase() + charId.slice(1));
        setCharacterAvatar(charName);
    }

    function setVal(id, val) {
        const el = document.getElementById(id);
        if (el && val) el.value = val;
    }

    function setOpt(id, val) {
        const sel = document.getElementById(id);
        if (!sel || !val) return;
        if (!Array.from(sel.options).some(o => o.value === val)) {
            const o = document.createElement('option');
            o.value = val; o.textContent = val;
            sel.appendChild(o);
        }
        sel.value = val;
    }

    
    const charSearchInput = document.getElementById('char-search-input');
    charSearchInput.addEventListener('input', () => {
        const q = charSearchInput.value.toLowerCase();
        document.querySelectorAll('#characters-grid .char-card').forEach(card => {
            const text = card.dataset.search || '';
            card.style.display = text.includes(q) ? '' : 'none';
        });
    });

    async function loadCharacters() {
        const grid = document.getElementById('characters-grid');
        if (!grid) return;
        // Show skeleton loading
        grid.innerHTML = Array(3).fill('').map(() => `
            <div class="char-card" aria-hidden="true">
                <div class="skeleton skeleton-circle"></div>
                <div class="char-info">
                    <div class="skeleton skeleton-text" style="width:40%"></div>
                    <div class="skeleton skeleton-text"></div>
                </div>
            </div>
        `).join('');
        grid.setAttribute('aria-busy', 'true');

        const chars = await api(BASE_URL + '/api/characters');
        if (!chars) {
            grid.innerHTML = `<p class="muted" style="padding:1rem">${t('characters.no_characters') || 'No characters found'}</p>`;
            grid.removeAttribute('aria-busy');
            return;
        }
        const s = await api(BASE_URL + '/api/settings');
        const active = s?.character?.active || 'amalgam';
        grid.innerHTML = '';
        grid.removeAttribute('aria-busy');

        for (const [id, c] of Object.entries(chars)) {
            const card = document.createElement('div');
            card.className = `char-card ${id === active ? 'active' : ''}`;
            let iconUrl = c.icon_url || './icons/logo.png';
            if (iconUrl.startsWith('/')) iconUrl = BASE_URL + iconUrl;
            const searchText = [id, c.name, c.description, c.personality, c.voice].filter(Boolean).join(' ').toLowerCase();
            card.dataset.search = searchText;
            card.innerHTML = `
                <img src="${iconUrl}" alt="${c.name} avatar" class="char-avatar" onerror="this.src='./icons/logo.png'">
                <div class="char-info">
                    <h3>${escHtml(c.name || id)}</h3>
                    <p>${escHtml(c.description || '')}</p>
                    <div class="char-tags">
                        ${c.personality ? `<span class="tag">${c.personality}</span>` : ''}
                        ${c.voice ? `<span class="tag tag-voice">${c.voice.split('-').pop().replace('Neural', '')}</span>` : ''}
                    </div>
                </div>
            `;
            const charName = c.name || id;
            card.addEventListener('click', async () => {
                const body = { character: { active: id } };
                if (c.voice) body.voice = { active: c.voice };
                await api(BASE_URL + '/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                grid.querySelectorAll('.char-card').forEach(el => el.classList.remove('active'));
                card.classList.add('active');
                setCharacterAvatar(charName);
        await fetchCommands();
                
                let vrmPath = c.model_url || '/characters/default/model.vrm';
                if (vrmPath.startsWith('/')) vrmPath = BASE_URL + vrmPath;
                if (avatarRenderer) avatarRenderer.loadVRM(vrmPath);
                if (avatarPreviewRenderer) avatarPreviewRenderer.loadVRM(vrmPath);
                _vrmPath = vrmPath;
                
                await api(BASE_URL + '/api/settings/set', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: 'avatar.model_path', value: vrmPath.replace(/^\/+/, '') })
                });
                showToast(`Switched to ${c.name || id}`);
            });
            grid.appendChild(card);
        }
    }



    
    async function loadMCP() {
        const servers = await api(BASE_URL + '/api/mcp/servers');
        const tools = await api(BASE_URL + '/api/mcp/tools');
        const list = document.getElementById('mcp-toggle-list');
        const grid = document.getElementById('tools-grid');

        if (servers?.servers) {
            mcpServersCache = servers.servers; 
            list.innerHTML = '';
            servers.servers.forEach(s => {
                const item = document.createElement('div');
                item.className = `mcp-item${s.enabled === false ? ' disabled' : ''}`;
                const icon = s.enabled !== false ? 'check_circle' : 'cancel';
                const iconClass = s.enabled !== false ? 'online' : 'offline';
                const connClass = s.connected ? 'connected' : 'disconnected';
                item.innerHTML = `
                    <div class="mcp-item-info">
                        <span class="material-icons-round mcp-status-icon ${iconClass}">${icon}</span>
                        <div>
                            <strong><span class="conn-dot ${connClass}"></span> ${escHtml(s.name)}</strong>
                            <span class="muted">${escHtml((() => { const c = s.command + ' ' + (s.args || []).join(' '); return c.length > 40 ? c.slice(0, 40) + '...' : c; })())}</span>
                        </div>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" class="mcp-enabled" data-name="${escHtml(s.name)}" ${s.enabled !== false ? 'checked' : ''}>
                        <span class="toggle-slider"></span>
                    </label>
                `;
                const checkbox = item.querySelector('.mcp-enabled');
                checkbox.addEventListener('change', () => {
                    const isEnabled = checkbox.checked;
                    const statusIcon = item.querySelector('.mcp-status-icon');
                    statusIcon.textContent = isEnabled ? 'check_circle' : 'cancel';
                    statusIcon.className = `material-icons-round mcp-status-icon ${isEnabled ? 'online' : 'offline'}`;
                    item.classList.toggle('disabled', !isEnabled);
                    const server = mcpServersCache.find(srv => srv.name === s.name);
                    if (server) server.enabled = isEnabled;
                    // Persist MCP state
                    const payload = { settings: { 'mcp.servers': mcpServersCache } };
                    fetch(`${BASE_URL}/api/settings/batch`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    }).catch(() => {});
                });
                list.appendChild(item);
            });
        }

        if (tools?.tools) {
            
            const enabledServers = new Set(
                (servers?.servers || []).filter(s => s.enabled !== false).map(s => s.name)
            );
            
            const enabledTools = tools.tools.filter(t => {
                
                return true; 
            });

            grid.innerHTML = enabledTools.length === 0
                ? '<p class="muted">No tools connected</p>'
                : '';
            enabledTools.forEach(t => {
                const card = document.createElement('div');
                card.className = 'tool-card';
                const desc = (t.description || '').length > 40 ? (t.description || '').slice(0, 40) + '...' : (t.description || '');
                card.innerHTML = `<strong>${escHtml(t.name)}</strong><p>${escHtml(desc)}</p>`;
                grid.appendChild(card);
            });
        }
    }

    
    async function loadRelationship() {
        const charId = (await api(BASE_URL + '/api/settings'))?.character?.active || 'amalgam';
        const data = await api(BASE_URL + `/api/relationship/${charId}`);
        const container = document.getElementById('relationship-display');
        const label = document.getElementById('rel-stage-label');
        if (!container) return;
        if (!data || data.error) {
            container.innerHTML = '<p class="muted">No relationship data yet.</p>';
            if (label) label.textContent = '';
            return;
        }
        if (label) label.textContent = data.stage || '';
        container.innerHTML = `
            <div class="rel-stat"><span class="rel-stat-label">Stage</span><span>${data.stage || 'stranger'}</span></div>
            <div class="rel-stat"><span class="rel-stat-label">Interactions</span><span>${data.interaction_count || 0}</span></div>
            <div class="rel-stat"><span class="rel-stat-label">Sentiment</span><span>${data.avg_sentiment ?? 0.5}</span></div>
            <div class="rel-stat"><span class="rel-stat-label">Depth</span><span>${data.avg_depth ?? 0}</span></div>
            <div class="rel-stat"><span class="rel-stat-label">User words</span><span>${data.total_words_user || 0}</span></div>
            <div class="rel-stat"><span class="rel-stat-label">Assistant words</span><span>${data.total_words_assistant || 0}</span></div>
        `;
    }

    async function loadSessions() {
        const data = await api(BASE_URL + '/api/memory/sessions');
        const container = document.getElementById('sessions-list');
        const count = document.getElementById('sessions-count');
        if (!container) return;
        const sessions = data?.sessions || [];
        if (count) count.textContent = `(${sessions.length})`;
        if (sessions.length === 0) {
            container.innerHTML = '<p class="muted">No sessions yet.</p>';
            return;
        }
        container.innerHTML = sessions.map(s => `
            <div class="data-session-item">
                <strong>${escHtml(s.title || s.id)}</strong>
                <span class="muted">${s.message_count || '?'} msgs</span>
                <span class="data-session-delete" data-id="${s.id}">delete</span>
            </div>
        `).join('');
        container.querySelectorAll('.data-session-delete').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (!confirm('Delete this session?')) return;
                await api(BASE_URL + `/api/memory/session/${btn.dataset.id}`, { method: 'DELETE' });
                loadSessions();
                loadHistory();
                showToast('Session deleted');
            });
        });
    }

    const settingsTab = document.getElementById('tab-settings');
    if (settingsTab) {
        const observer = new MutationObserver(() => {
            if (settingsTab.classList.contains('active')) {
                renderSettings();
                _attachSettingsDelegates();
                loadRelationship();
                loadSessions();
                loadHistory(); 
            }
        });
        observer.observe(settingsTab, { attributes: true, attributeFilter: ['class'] });
        
        if (settingsTab.classList.contains('active')) {
            renderSettings();
            _attachSettingsDelegates();
            loadRelationship();
            loadSessions();
            loadHistory(); 
        }
    }

    
    const historyPanel = document.getElementById('history-panel');
    const historyList = document.getElementById('history-list');

    document.getElementById('new-chat-btn').addEventListener('click', async () => {
        const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
        if (res?.session_id) location.hash = 'chat/' + res.session_id;
        showToast('New conversation started');
    });

    document.getElementById('history-toggle').addEventListener('click', async () => {
        console.log('History toggle clicked');
        historyPanel.classList.toggle('open');
        const isVisible = historyPanel.classList.contains('open');
        document.getElementById('history-toggle').setAttribute('aria-expanded', isVisible);
        console.log('History panel open class:', isVisible);
        if (historyPanel.classList.contains('open')) {
            console.log('Loading history...');
            await loadHistory();
        }
    });
    document.getElementById('close-history').addEventListener('click', () => {
        historyPanel.classList.remove('open');
    });

    document.getElementById('new-session-btn').addEventListener('click', async () => {
        const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
        if (res?.session_id) location.hash = 'chat/' + res.session_id;
        historyPanel.classList.remove('open');
        showToast('New conversation started');
    });

    document.getElementById('clear-all-history').addEventListener('click', async () => {
        if (!confirm('Clear all conversation history?')) return;
        await api(BASE_URL + '/api/memory/clear', { method: 'POST' });
        const res = await api(BASE_URL + '/api/memory/session/current');
        if (res?.session_id) location.hash = 'chat/' + res.session_id;
        historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">No conversations yet</div>';
        updateHistoryToggle();
        showToast('History cleared');
    });

    function updateHistoryToggle() {
        const hasSessions = !!historyList.querySelector('[data-session-id]');
        document.getElementById('history-toggle').style.display = hasSessions ? '' : 'none';
    }

    let _historyLoadInProgress = false;

    async function loadHistory() {
        if (_historyLoadInProgress) return;
        _historyLoadInProgress = true;
        const container = document.getElementById('history-list');
        if (!container) return;
        try {
            const data = await api(BASE_URL + '/api/memory/sessions');
            console.log('loadHistory: API response:', data);
            historyList.innerHTML = '';
            if (!data || !data.sessions || data.sessions.length === 0) {
                historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">No conversations yet</div>';
                updateHistoryToggle();
                return;
            }
            console.log('loadHistory: got', data.sessions.length, 'sessions');
            data.sessions.forEach(session => {
                const item = document.createElement('div');
                item.className = 'history-item';
                item.dataset.sessionId = session.id;
                const time = session.last_active ? new Date(session.last_active).toLocaleString([], { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' }) : '';
                item.innerHTML = `
                    <div class="history-content">
                        <div class="history-preview">${escHtml(session.preview)}</div>
                        <div class="history-time">${time} · ${session.message_count} messages</div>
                    </div>
                    <button class="history-delete" title="Delete conversation"><span class="material-icons-round" style="font-size:1rem">close</span></button>
                `;
                item.querySelector('.history-content').addEventListener('click', async () => {
                    location.hash = 'chat/' + session.id;
                    historyPanel.classList.remove('open');
                });
                item.querySelector('.history-delete').addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (!confirm('Delete this conversation?')) return;
                    await api(BASE_URL + `/api/memory/session/${session.id}`, { method: 'DELETE' });
                    item.remove();
                    if (location.hash.replace('#', '').split('/')[1] === session.id) {
                        const res = await api(BASE_URL + '/api/memory/new-session', { method: 'POST' });
                        if (res?.session_id) location.hash = 'chat/' + res.session_id;
                    }
                    updateHistoryToggle();
                });
                
                historyList.appendChild(item);
            });
            updateHistoryToggle();
        } catch (e) {
            historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted)">Failed to load history</div>';
            updateHistoryToggle();
        } finally {
            _historyLoadInProgress = false;
        }
    }

    
    const historySearchInput = document.getElementById('history-search-input');
    let _historySearchTimer = null;
    let _historySearchAbort = null;

    if (historySearchInput) {
        historySearchInput.addEventListener('input', () => {
            clearTimeout(_historySearchTimer);
            const q = historySearchInput.value.trim();
            if (!q) {
                loadHistory();
                return;
            }
            _historySearchTimer = setTimeout(() => performHistorySearch(q), 300);
        });
    }

    async function performHistorySearch(query) {
        if (_historySearchAbort) _historySearchAbort.abort();
        _historySearchAbort = new AbortController();
        try {
            const res = await fetch(
                `${BASE_URL}/api/memory/search?q=${encodeURIComponent(query)}&scope=all`,
                { signal: _historySearchAbort.signal }
            );
            const data = await res.json();
            renderHistorySearchResults(data.results || []);
        } catch (e) {
            if (e.name !== 'AbortError') console.warn('History search failed:', e);
        }
    }

    function renderHistorySearchResults(results) {
        historyList.innerHTML = '';
        if (results.length === 0) {
            historyList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">No results found</div>';
            return;
        }
        results.forEach(r => {
            const item = document.createElement('div');
            item.className = 'history-search-result';
            const snippet = r.content ? r.content.substring(0, 120) : '';
            item.innerHTML = `
                <div class="result-session">${escHtml(r.session_id || 'unknown')}</div>
                <div class="result-snippet">${escHtml(snippet)}</div>
            `;
            item.addEventListener('click', () => {
                location.hash = 'chat/' + r.session_id;
                historyPanel.classList.remove('open');
            });
            historyList.appendChild(item);
        });
    }

    

    
    function hideShellPermission() {
        const overlay = document.getElementById('shell-permission-overlay');
        if (overlay) overlay.style.display = 'none';
    }

    async function approveShellCommand(mode) {
        const cmdDisplay = document.getElementById('shell-pending-cmd');
        const cmd = cmdDisplay?.textContent || '';
        if (!cmd) return;
        hideShellPermission();
        if (mode === 'decline') {
            showToast('Command declined');
            return;
        }
        await api(BASE_URL + '/api/shell/approve', {
            method: 'POST',
            body: JSON.stringify({ cmd, mode })
        });
        showToast(`Command ${mode === 'once' ? 'allowed once' : mode === 'prefix' ? 'prefix allowed' : 'exact command allowed'}. Re-send your message to retry.`);
    }

    document.getElementById('shell-allow-once')?.addEventListener('click', () => approveShellCommand('once'));
    document.getElementById('shell-allow-prefix')?.addEventListener('click', () => approveShellCommand('prefix'));
    document.getElementById('shell-allow-exact')?.addEventListener('click', () => approveShellCommand('exact'));
    document.getElementById('shell-decline')?.addEventListener('click', () => approveShellCommand('decline'));

    
    initCustomSelects();
    connectWS();
    init().catch(e => {
        console.error('Init failed:', e);
        showToast('Failed to connect to server', 'danger');
        _initComplete = true;
    });

    // 6A.4 — Keyboard avoidance via visualViewport API
    if (window.visualViewport) {
        const adjustForKeyboard = () => {
            const chatInput = document.querySelector('.chat-input-area');
            if (!chatInput) return;
            const diff = window.innerHeight - window.visualViewport.height;
            if (diff > 100) {
                // Keyboard is open — shift input above keyboard
                chatInput.style.position = 'fixed';
                chatInput.style.bottom = (window.innerHeight - window.visualViewport.height) + 'px';
                chatInput.style.left = '0';
                chatInput.style.right = '0';
                chatInput.style.zIndex = '1001';
            } else {
                chatInput.style.position = '';
                chatInput.style.bottom = '';
                chatInput.style.left = '';
                chatInput.style.right = '';
                chatInput.style.zIndex = '';
            }
        };
        window.visualViewport.addEventListener('resize', adjustForKeyboard);
        window.visualViewport.addEventListener('scroll', adjustForKeyboard);
    }

    // Add CSS animation for test connection spinner
    const _styleSheet = document.createElement('style');
    _styleSheet.textContent = `
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .test-conn-btn .material-icons-round { font-size: 18px; }
    `;
    document.head.appendChild(_styleSheet);

    // Periodic health refresh
    const _healthInterval = setInterval(refreshHealth, 30000); // every 30s
    window.addEventListener('beforeunload', () => clearInterval(_healthInterval));
    refreshHealth(); // initial fetch

    // Online/offline detection
    window.addEventListener('online', () => {
        const bar = document.getElementById('offline-bar');
        if (bar) {
            bar.classList.add('hidden');
            bar.classList.remove('visible');
        }
        // Reconnect WebSocket if not already connected/connecting
        if (ws && ws.readyState !== WebSocket.OPEN && ws.readyState !== WebSocket.CONNECTING) {
            connectWS();
        }
    });

    window.addEventListener('offline', () => {
        const bar = document.getElementById('offline-bar');
        if (bar) {
            bar.classList.remove('hidden');
            bar.classList.add('visible');
        }
    });
});

// Health bar management
function updateHealthBar(services) {
    for (const [name, state] of Object.entries(services)) {
        const dot = document.querySelector(`.health-dot[data-service="${name}"]`);
        if (dot) {
            dot.dataset.status = state.status;
            dot.title = `${name.toUpperCase()}: ${state.status}${state.detail ? ' — ' + state.detail : ''}`;
        }
    }
}

// Fetch health status periodically
async function refreshHealth() {
    try {
        const resp = await fetch(`${BASE_URL}/api/health`);
        if (resp.ok) {
            const data = await resp.json();
            if (data.services) {
                updateHealthBar(data.services);
            }
        }
    } catch (e) {
        // Silently fail — health bar just stays unknown
    }
}

// 6A.5 — GPU capability detection
function detectGPUCapability() {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl) return { tier: 'software', reason: 'no-webgl' };

    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = debugInfo ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) : '';
    const vendor = debugInfo ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) : '';
    const maxTexSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);

    const isLowEnd = /(adreno 5|adreno 4|mali-?4|mali-?3|powervr|intel hd graphics|swiftshader|llvmpipe)/i.test(renderer);
    const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry/i.test(navigator.userAgent);
    const isVeryLowTex = maxTexSize < 4096;

    if (isLowEnd || isVeryLowTex) {
        return { tier: 'low', reason: renderer, renderer, vendor };
    }
    if (isMobile) {
        return { tier: 'medium', reason: renderer, renderer, vendor };
    }
    return { tier: 'high', reason: renderer, renderer, vendor };
}

const gpuInfo = detectGPUCapability();
window._gpuTier = gpuInfo.tier;
console.log(`GPU tier: ${gpuInfo.tier} (${gpuInfo.reason})`);

/* ==================== PWA Polish: Install, Reduced Motion, Focus Management ==================== */

// PWA Install prompt
let deferredInstallPrompt = null;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    const banner = document.getElementById('install-banner');
    if (banner) {
        banner.classList.remove('hidden');
        banner.classList.add('visible');
    }
});

window.addEventListener('appinstalled', () => {
    const banner = document.getElementById('install-banner');
    if (banner) {
        banner.classList.add('hidden');
        banner.classList.remove('visible');
    }
    deferredInstallPrompt = null;
});

document.addEventListener('click', async (e) => {
    const installBtn = e.target.closest('#install-btn');
    if (installBtn && deferredInstallPrompt) {
        deferredInstallPrompt.prompt();
        const result = await deferredInstallPrompt.userChoice;
        if (result.outcome === 'accepted') {
            console.log('PWA installed');
        }
        deferredInstallPrompt = null;
        const banner = document.getElementById('install-banner');
        if (banner) {
            banner.classList.add('hidden');
            banner.classList.remove('visible');
        }
        return;
    }

    const dismissBtn = e.target.closest('#install-dismiss');
    if (dismissBtn) {
        const banner = document.getElementById('install-banner');
        if (banner) {
            banner.classList.add('hidden');
            banner.classList.remove('visible');
        }
        deferredInstallPrompt = null;
    }
});

// Reduced motion preference detection
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
if (prefersReducedMotion.matches) {
    document.body.classList.add('reduced-motion');
}
prefersReducedMotion.addEventListener('change', (e) => {
    document.body.classList.toggle('reduced-motion', e.matches);
});

// Focus management for modal overlays
function trapFocus(modalElement) {
    if (!modalElement) return;
    const focusable = modalElement.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    const handler = (e) => {
        if (e.key !== 'Tab') return;
        if (e.shiftKey) {
            if (document.activeElement === first) {
                e.preventDefault();
                last?.focus();
            }
        } else {
            if (document.activeElement === last) {
                e.preventDefault();
                first?.focus();
            }
        }
    };

    modalElement.addEventListener('keydown', handler);
    modalElement._trapFocusHandler = handler;

    if (first) setTimeout(() => first.focus(), 50);
}

// Settings open/close (tab-based settings panel)
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

/* ---------- Setup wizard functions ---------- */

let _setupMode = null;        // 'minimal' | 'advanced'
let _setupProviders = [];     // cached from /api/providers
let _selectedProvider = null; // current provider id in step 1
let _setupCurrentStep = 1;    // 1-based (step 0 = welcome)

async function showSetupWizard() {
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
    // Hide all steps
    document.querySelectorAll('.setup-step').forEach(s => s.style.display = 'none');
    // Show target
    const el = document.getElementById('setup-' + step);
    if (el) {
        el.style.display = 'flex';
        // Focus first focusable element
        const first = el.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        setTimeout(() => first?.focus(), 100);
    }
}

function _initSetupWizard() {
    // ── Mode selection ──
    const minimalCard = document.getElementById('setup-mode-minimal');
    const advancedCard = document.getElementById('setup-mode-advanced');
    if (minimalCard) {
        minimalCard.addEventListener('click', () => _selectSetupMode('minimal'));
        minimalCard.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _selectSetupMode('minimal'); } });
    }
    if (advancedCard) {
        advancedCard.addEventListener('click', () => _selectSetupMode('advanced'));
        advancedCard.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _selectSetupMode('advanced'); } });
    }

    // ── Back buttons ──
    document.getElementById('setup-back-step1')?.addEventListener('click', () => _showSetupStep('welcome'));
    document.getElementById('setup-back-step2')?.addEventListener('click', () => _showSetupStep('step1'));
    document.getElementById('setup-back-step3')?.addEventListener('click', () => _showSetupStep('step2'));

    // ── Provider selection (delegated) ──
    document.getElementById('setup-provider-grid')?.addEventListener('click', e => {
        const option = e.target.closest('.setup-provider-option');
        if (option) {
            const pid = option.dataset.providerId;
            if (pid) _selectSetupProvider(pid);
        }
    });

    // ── Test connection ──
    document.getElementById('setup-test-btn')?.addEventListener('click', testSetupConnection);

    // ── Continue button (step 1 → step 2/step3) ──
    document.getElementById('setup-continue-btn')?.addEventListener('click', () => _advanceFromStep1());

    // ── Voice continue (step 2 → step 3) ──
    document.getElementById('setup-voice-continue-btn')?.addEventListener('click', () => _showSetupStep('step3'));

    // ── Save (step 3) ──
    document.getElementById('setup-save-btn')?.addEventListener('click', saveSetupWizard);
}

function _selectSetupMode(mode) {
    _setupMode = mode;
    // Update card visuals
    document.querySelectorAll('.setup-mode-card').forEach(c => c.classList.remove('selected'));
    document.getElementById('setup-mode-' + mode)?.classList.add('selected');

    // Update step indicator
    const totalSteps = mode === 'minimal' ? '1' : '3';
    document.getElementById('setup-total-steps').textContent = totalSteps;
    document.getElementById('setup-total-steps2').textContent = totalSteps;
    document.getElementById('setup-total-steps3').textContent = totalSteps;
    if (mode === 'minimal') {
        document.getElementById('setup-step1-title').textContent = 'Choose Your Provider';
    } else {
        document.getElementById('setup-step1-title').textContent = 'Choose Your Provider';
    }

    // Load providers and move to step 1
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
        const data = await resp.json();
        _setupProviders = data.providers || [];

        // Render provider grid
        grid.innerHTML = _setupProviders.map(p => `
            <div class="setup-provider-option" data-provider-id="${p.id}" role="button" tabindex="0">
                <span>${escHtml(p.name)}</span>
                ${p.has_free_tier ? '<span class="provider-badge">Free</span>' : ''}
            </div>
        `).join('');

        loadingEl.style.display = 'none';
        listEl.style.display = 'block';
    } catch (e) {
        loadingEl.innerHTML = `<span class="material-icons-round" style="color:var(--danger)">error</span><span>Failed to load providers: ${e.message}</span>`;
    }
}

function _selectSetupProvider(pid) {
    _selectedProvider = pid;
    // Update grid visuals
    document.querySelectorAll('.setup-provider-option').forEach(el => {
        el.classList.toggle('selected', el.dataset.providerId === pid);
    });

    const provider = _setupProviders.find(p => p.id === pid);
    if (!provider) return;

    const detailEl = document.getElementById('setup-provider-detail');
    const apiKeyInput = document.getElementById('setup-api-key');
    const apiKeyDesc = document.getElementById('setup-api-key-desc');
    const modelSelect = document.getElementById('setup-model');
    const continueBtn = document.getElementById('setup-continue-btn');

    // Show/hide API key based on provider
    if (provider.needs_api_key) {
        apiKeyInput.style.display = '';
        apiKeyInput.required = true;
        apiKeyDesc.textContent = 'Your key stays on this device.';
    } else {
        apiKeyInput.style.display = 'none';
        apiKeyInput.required = false;
        apiKeyDesc.textContent = 'No API key needed for local providers.';
    }

    // Populate model dropdown
    modelSelect.innerHTML = '';
    if (provider.models && provider.models.length > 0) {
        provider.models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            modelSelect.appendChild(opt);
        });
        // Pre-select the default model
        if (provider.default_model) {
            modelSelect.value = provider.default_model;
        }
    } else {
        // No models list — show a placeholder
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'No preset models (type manually)';
        modelSelect.appendChild(opt);
        // Allow text input fallback by adding a datalist
        modelSelect.setAttribute('placeholder', 'Type model name');
    }

    detailEl.style.display = 'block';

    // Enable continue button (for minimal, or advanced step 1)
    _updateContinueButton();

    // Focus API key if visible
    if (provider.needs_api_key) {
        setTimeout(() => apiKeyInput?.focus(), 150);
    }
}

function _updateContinueButton() {
    const provider = _setupProviders.find(p => p.id === _selectedProvider);
    const apiKeyInput = document.getElementById('setup-api-key');
    const continueBtn = document.getElementById('setup-continue-btn');

    if (!provider) {
        continueBtn.disabled = true;
        return;
    }

    // For providers that need an API key, require it
    if (provider.needs_api_key) {
        const key = apiKeyInput?.value?.trim() || '';
        continueBtn.disabled = !key;
    } else {
        continueBtn.disabled = false;
    }
}

function _advanceFromStep1() {
    // For minimal mode, save directly (skip voice/character)
    if (_setupMode === 'minimal') {
        saveSetupWizard();
        return;
    }
    // For advanced mode, go to step 2 (voice)
    _showSetupStep('step2');
}

// Test connection from setup wizard
async function testSetupConnection() {
    const provider = _selectedProvider;
    const apiKey = document.getElementById('setup-api-key').value.trim();
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
        // Save key temporarily
        await fetch(`${BASE_URL}/api/settings/set`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: `provider.${provider}.api_key`, value: apiKey })
        });

        // Test the connection
        const resp = await fetch(`${BASE_URL}/api/settings/test/${provider}`, { method: 'POST' });
        const data = await resp.json();

        if (data.ok) {
            testResult.style.color = 'var(--success, #22c55e)';
            testResult.textContent = `✓ Connected (${data.latency_ms || '?'}ms)`;
            testResult.style.display = 'block';
        } else {
            testResult.style.color = 'var(--danger, #ef4444)';
            testResult.textContent = `✗ ${data.error || 'Connection failed'}`;
            testResult.style.display = 'block';
        }
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
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';
    }
    errorEl.style.display = 'none';

    try {
        // Use step1 endpoint which validates the connection
        const resp = await fetch(`${BASE_URL}/api/setup/step1`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, api_key: apiKey, model }),
        });
        const data = await resp.json();
        if (data.ok || !provObj?.needs_api_key) {
            if (_setupMode === 'advanced') {
                // Voice step
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
                // Character step
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
                // Minimal: just mark setup complete with defaults for voice/character
                await fetch(`${BASE_URL}/api/setup/step2`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                await fetch(`${BASE_URL}/api/setup/step3`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
            }

            // Show done
            _showSetupStep('wizard-done');
            setTimeout(hideSetupWizard, 2000);

            // Refresh settings
            fetch(`${BASE_URL}/api/settings`).then(r => r.json()).then(s => {
                window._settingsCache = s;
            }).catch(() => {});
        } else {
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save & Start Chatting';
            }
            errorEl.textContent = data.error || data.detail || 'Connection failed. Check your API key and try again.';
            errorEl.style.display = 'block';
        }
    } catch (e) {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save & Start Chatting';
        }
        errorEl.textContent = `Error: ${e.message}`;
        errorEl.style.display = 'block';
    }
}

// Watch API key input to enable/disable continue button
document.addEventListener('DOMContentLoaded', () => {
    // Lazy-init the wizard event listeners
    _initSetupWizard();

    // Delegate API key changes
    document.addEventListener('input', e => {
        if (e.target.id === 'setup-api-key') {
            _updateContinueButton();
        }
    });

    const saveBtn = document.getElementById('setup-save-btn');
    if (saveBtn) saveBtn.addEventListener('click', saveSetupWizard);
    const testBtn = document.getElementById('setup-test-btn');
    if (testBtn) testBtn.addEventListener('click', testSetupConnection);
});
