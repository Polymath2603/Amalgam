/**
 * settings-schema.js — Data-driven settings form definitions
 * Zero dependencies.
 */

export const PROVIDER_DISPLAY_NAMES = {
    'gemini': 'Google Gemini',
    'openai': 'OpenAI (ChatGPT)',
    'anthropic': 'Anthropic (Claude)',
    'groq': 'Groq',
    'ollama': 'Ollama (Local)',
    'openrouter': 'OpenRouter',
    'deepseek': 'DeepSeek',
    'mistral': 'Mistral',
    'together': 'Together AI',
    'siliconflow': 'SiliconFlow',
    'zai': 'ZAI (Turing/LLM-ZH)',
    'huggingface': 'Hugging Face Inference',
    'llamacpp': 'llama.cpp (Local)',
    'koboldai': 'KoboldAI (Local)',
    'azure-openai': 'Azure OpenAI',
    'alibaba': 'Alibaba Cloud (DashScope)',
    'aws': 'AWS Bedrock',
    'gcp': 'GCP Vertex AI',
    'opencode': 'OpenCode',
};

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
            companion_mode: {
                label: "Companion Mode",
                type: "toggle",
                key: "behavior.companion_enabled",
                description: "Enable proactive companion interactions",
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
                options: ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
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
    "Companion": {
        icon: "pets",
        fields: {
            companion_enabled: {
                label: "Enable Companion",
                type: "toggle",
                key: "companion.enabled",
                description: "Enable proactive companion interactions",
            },
            companion_idle_check_delay: {
                label: "Idle Check-In Delay (min)",
                type: "number",
                key: "companion.idle_check_delay",
                min: 1, max: 120, step: 1,
                description: "Minutes of inactivity before the companion checks in",
            },
            companion_proactive_interval: {
                label: "Proactive Interval (min)",
                type: "number",
                key: "companion.proactive_interval",
                min: 10, max: 480, step: 10,
                description: "Minutes between proactive time-aware messages",
            },
            companion_time_awareness: {
                label: "Time Awareness",
                type: "toggle",
                key: "companion.time_awareness",
                description: "Send messages that acknowledge time of day",
            },
            companion_personality_notes: {
                label: "Personality Notes",
                type: "textarea",
                key: "companion.personality_notes",
                description: "Extra personality instructions for the companion",
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
                key: "log.level",
                options: ["DEBUG", "INFO", "WARNING", "ERROR"],
                description: "Verbosity of application logs",
            },
        }
    },
};

export const PROVIDER_MODELS = {
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
