/**
 * settings-schema.js — Data-driven settings form definitions
 * Zero dependencies except fetch().
 *
 * All provider data and dropdown options are fetched dynamically from
 * backend APIs, not hardcoded. Static fallbacks exist only for when
 * the API is unreachable.
 */

// ── Dynamic provider data (populated from /api/providers) ────────────

export const PROVIDER_DISPLAY_NAMES = {};
export const PROVIDER_MODELS = {};

// ── Dynamic option caches (populated from various /api/ endpoints) ──

export const _optionsCache = {};

/**
 * Fetch a single dynamic option type from a backend endpoint.
 * Results are cached in _optionsCache[key].
 * Falls back to an empty array or a provided fallback on failure.
 */
export async function fetchOptions(key, url, fallback) {
    try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        // Support both { options: [...] } and [...] response shapes
        const list = Array.isArray(data) ? data : (data.options || data[key] || []);
        _optionsCache[key] = list;
        return list;
    } catch (e) {
        console.warn(`fetchOptions(${key}): ${e.message}, using fallback`);
        _optionsCache[key] = fallback || [];
        return _optionsCache[key];
    }
}

let _dynamicInitPromise = null;

/**
 * Populate all option caches from the backend.
 * Called before settings rendering so that dynamic selects show live data.
 */
export async function initDynamicOptions() {
    if (_dynamicInitPromise) return _dynamicInitPromise;
    _dynamicInitPromise = Promise.all([
        fetchOptions('stt_engines', '/api/settings/options/stt_engines', ['browser', 'faster-whisper', 'openai-whisper', 'groq-whisper', 'whispercpp']),
        fetchOptions('tts_engines', '/api/settings/options/tts_engines', ['edge-tts', 'openvoice', 'elevenlabs', 'openai-tts', 'speecht5', 'alltalk', 'piper', 'coqui-local', 'kokoro']),
        fetchOptions('openai_tts_voices', '/api/settings/options/openai_tts_voices', ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer']),
        fetchOptions('themes', '/api/settings/options/themes', ['dark', 'midnight', 'light', 'nord']),
        fetchOptions('languages', '/api/settings/options/languages', ['en', 'zh']),
        fetchOptions('profiles', '/api/settings/options/profiles', ['default', 'token-friendly', 'quality', 'custom']),
        fetchOptions('translation_languages', '/api/settings/options/translation_languages', ['auto', 'en', 'zh', 'ja', 'ko', 'fr', 'de', 'es', 'pt', 'ru', 'ar', 'th', 'vi']),
        fetchOptions('vad_modes', '/api/settings/options/vad_modes', ['0', '1', '2', '3']),
        fetchOptions('log_levels', '/api/settings/options/log_levels', ['DEBUG', 'INFO', 'WARNING', 'ERROR']),
    ]);
    return _dynamicInitPromise;
}

/**
 * Invalidate a specific cache entry so it is re-fetched on next access.
 */
export function invalidateOptionsCache(key) {
    delete _optionsCache[key];
}

/**
 * Invalidate all option caches so they are re-fetched.
 */
export function invalidateAllOptionsCache() {
    Object.keys(_optionsCache).forEach(k => delete _optionsCache[k]);
    _dynamicInitPromise = null;
}

// ── Provider data from /api/providers (single source of truth) ────────

let _providerDataInitPromise = null;

/**
 * Fetch provider data from the backend and populate PROVIDER_DISPLAY_NAMES
 * and PROVIDER_MODELS.  Called automatically at module load time.
 * No hardcoded fallback values — the live API data IS the source of truth.
 */
export async function initProviderData() {
    if (_providerDataInitPromise) return _providerDataInitPromise;
    _providerDataInitPromise = (async () => {
        try {
            const resp = await fetch('/api/providers');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            const providers = data.providers || [];
            // Clear and repopulate from API
            Object.keys(PROVIDER_DISPLAY_NAMES).forEach(k => delete PROVIDER_DISPLAY_NAMES[k]);
            Object.keys(PROVIDER_MODELS).forEach(k => delete PROVIDER_MODELS[k]);
            for (const p of providers) {
                PROVIDER_DISPLAY_NAMES[p.id] = p.name;
                if (Array.isArray(p.models)) {
                    PROVIDER_MODELS[p.id] = p.models;
                }
            }
        } catch (e) {
            console.warn('initProviderData: failed to fetch /api/providers:', e);
        }
    })();
    return _providerDataInitPromise;
}

// Start fetching at module load time so data is ready before first render.
initProviderData();

export const SETTINGS_SCHEMA = {
    "Character": {
        icon: "person",
        fields: {
            active_character: {
                label: "Active Character",
                type: "select",
                key: "character.active",
                dynamic_characters: true,
                description: "Which character personality to use",
            },
            char_info: {
                label: "Character Info",
                type: "info",
                key: "_char_info",
                description: "Name, personality and voice of the active character",
            },
            thinking: {
                label: "Show Thinking",
                type: "toggle",
                key: "ui.thinking_enabled",
                description: "Display reasoning before responses",
            },
            greeting: {
                label: "Greeting",
                type: "text",
                key: "character.greeting",
                description: "First message the character sends on new conversations",
            },
            character_rules: {
                label: "Behavior Rules",
                type: "textarea",
                key: "character.rules",
                description: "Rules the character must follow during conversations",
            },
            system_prompt: {
                label: "Additional Instructions",
                type: "textarea",
                key: "character.system_prompt",
                description: "Extra instructions appended to every conversation",
            },
        }
    },
    "Provider": {
        icon: "cloud",
        fields: {
            active_provider: {
                label: "Active Provider",
                type: "select",
                key: "provider.active",
                dynamic_providers: true,
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
            aws_model: {
                label: "Model",
                type: "select",
                key: "provider.aws.model",
                show_if: { field: "active_provider", equals: "aws" },
                dynamic_options: true,
                dynamic_options_provider: "aws",
                description: "Bedrock model ID (fetched from backend)",
            },
            gcp_model: {
                label: "Model",
                type: "select",
                key: "provider.gcp.model",
                show_if: { field: "active_provider", equals: "gcp" },
                dynamic_options: true,
                dynamic_options_provider: "gcp",
                description: "Vertex AI model name (fetched from backend)",
            },
        }
    },
    "Voice": {
        icon: "record_voice_over",
        fields: {
            stt_engine: {
                label: "Speech-to-Text Engine",
                type: "select",
                key: "voice.stt_engine_webui",
                dynamic_fetch: "stt_engines",
                description: "Engine for converting speech to text (WebUI mode)",
                onChange: "refreshCategory",
            },
            tts_engine: {
                label: "Text-to-Speech Engine",
                type: "select",
                key: "voice.engine",
                dynamic_fetch: "tts_engines",
                description: "Engine for converting text to speech",
                onChange: "refreshCategory",
            },
            voice_input: {
                label: "Voice Input (Mic)",
                type: "toggle",
                key: "ui.voice_input",
                description: "Enable microphone input",
            },
            voice_output: {
                label: "Voice Output (Speaker)",
                type: "toggle",
                key: "ui.voice_output",
                description: "Enable speech output",
            },
            lipsync: {
                label: "Lip-sync",
                type: "toggle",
                key: "voice.lipsync_enabled",
                description: "Animate avatar mouth with speech",
            },
            fw_model: {
                label: "Faster-Whisper Model Size",
                type: "select",
                key: "voice.faster_whisper.model",
                options: ["tiny", "base", "small", "medium", "large"],
                show_if: { field: "stt_engine", equals: "faster-whisper" },
            },
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
            wcpp_url: {
                label: "Whisper.cpp URL",
                type: "text",
                key: "voice.whispercpp.url",
                show_if: { field: "stt_engine", equals: "whispercpp" },
            },
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
                dynamic_fetch: "openai_tts_voices",
                show_if: { field: "tts_engine", equals: "openai-tts" },
            },
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
            piper_url: {
                label: "Piper URL",
                type: "text",
                key: "voice.piper.url",
                show_if: { field: "tts_engine", equals: "piper" },
            },
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
    "Translation": {
        icon: "translate",
        fields: {
            translation_enabled: {
                label: "Translation Enabled",
                type: "toggle",
                key: "translation.enabled",
                description: "Translate assistant responses via DeepLX before TTS",
            },
            translation_source_lang: {
                label: "Source Language",
                type: "select",
                key: "translation.source_lang",
                dynamic_fetch: "translation_languages",
                description: "Language of the original text (auto = detect)",
            },
            translation_target_lang: {
                label: "Target Language",
                type: "select",
                key: "translation.target_lang",
                dynamic_fetch: "translation_languages",
                description: "Language to translate responses into",
            },
            translation_base_url: {
                label: "DeepLX Server URL",
                type: "text",
                key: "translation.base_url",
                description: "Self-hosted DeepLX API endpoint (default: http://localhost:1188/translate)",
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
                dynamic_fetch: "themes",
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
                dynamic_fetch: "languages",
                description: "Interface language",
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
    "Advanced": {
        icon: "tune",
        fields: {
            profile: {
                label: "Settings Profile",
                type: "select",
                key: "profile",
                dynamic_fetch: "profiles",
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
                dynamic_fetch: "vad_modes",
                description: "Voice Activity Detection aggressiveness",
            },
            log_level: {
                label: "Log Level",
                type: "select",
                key: "log.level",
                dynamic_fetch: "log_levels",
                description: "Verbosity of application logs",
            },
        }
    },
};

// ── Provider data from /api/providers (single source of truth) ────────
// Legacy re-exports for backward compatibility
export { _optionsCache as optionsCache };
