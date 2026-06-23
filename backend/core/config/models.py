"""
Typed settings models for Amalgam using Pydantic.

Replaces the flat ``Dict[str, Any]`` approach with validated, autocomplete-friendly
models.  Every category from ``DEFAULTS`` in ``settings.py`` has a corresponding
model class, and ``AppSettings.model_dump_flat()`` provides a backwards-compatible
dot‑notation dict for code that hasn't migrated yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


# =============================================================================
# ── Provider sub‑configs ──
# =============================================================================


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Generic OpenAI‑compatible provider configuration."""

    api_key: SecretStr = Field(default=SecretStr(""), description="API key for the provider")
    model: str = Field(default="", description="Model identifier")
    base_url: str = Field(default="", description="Base URL for API calls")
    timeout: int = Field(default=30, ge=5, le=120, description="Request timeout in seconds")
    max_tokens: int = Field(default=4096, ge=256, le=8192, description="Maximum tokens per response")


class AWSConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """AWS Bedrock provider configuration."""

    access_key: str = Field(default="", description="AWS access key")
    secret_key: str = Field(default="", description="AWS secret key")
    region: str = Field(default="us-east-1", description="AWS region")
    model: str = Field(default="anthropic.claude-sonnet-4-20250514", description="Bedrock model ID")


class GCPConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """GCP Vertex AI provider configuration."""

    service_account_json: str = Field(default="", description="GCP service account JSON key")
    project_id: str = Field(default="", description="GCP project ID")
    region: str = Field(default="us-central1", description="GCP region")
    model: str = Field(default="gemini-2.0-flash-001", description="Vertex AI model name")


class LLMProviderConfig(BaseModel):
    """All provider configurations and the active provider selection."""

    active: Literal[
        "gemini",
        "ollama",
        "openrouter",
        "zai",
        "siliconflow",
        "groq",
        "chatgpt",
        "claude",
        "llamacpp",
        "koboldai",
        "deepseek",
        "mistral",
        "together",
        "azure-openai",
        "alibaba",
        "huggingface",
        "aws",
        "gcp",
        "opencode",
    ] = Field(default="gemini", description="Active LLM provider key")

    ollama: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(base_url="http://localhost:11434", api_key=SecretStr(""), model="", timeout=30, max_tokens=4096),
        description="Ollama (local) provider",
    )
    gemini: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="gemini-2.5-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            timeout=30,
            max_tokens=4096,
        ),
        description="Google Gemini provider",
    )
    openrouter: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="meta-llama/llama-3.1-8b-instruct:free",
            base_url="https://openrouter.ai/api/v1",
            timeout=30,
            max_tokens=4096,
        ),
        description="OpenRouter provider",
    )
    zai: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="GLM-5.1",
            base_url="https://api.z.ai/api/coding/paas/v4",
            timeout=30,
            max_tokens=4096,
        ),
        description="Z.AI provider",
    )
    siliconflow: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="Qwen/Qwen2.5-7B-Instruct",
            base_url="https://api.siliconflow.cn/v1",
            timeout=30,
            max_tokens=4096,
        ),
        description="SiliconFlow provider",
    )
    groq: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="llama-3.3-70b-versatile",
            base_url="https://api.groq.com/openai/v1",
            timeout=30,
            max_tokens=4096,
        ),
        description="Groq provider",
    )
    chatgpt: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="gpt-4o-mini",
            base_url="https://api.openai.com/v1",
            timeout=30,
            max_tokens=4096,
        ),
        description="OpenAI ChatGPT provider",
    )
    claude: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="claude-sonnet-4-20250514",
            base_url="https://api.anthropic.com/v1",
            timeout=30,
            max_tokens=4096,
        ),
        description="Anthropic Claude provider",
    )
    llamacpp: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="",
            base_url="http://localhost:8080",
            timeout=30,
            max_tokens=4096,
        ),
        description="llama.cpp local provider",
    )
    koboldai: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="",
            base_url="http://localhost:5001",
            timeout=30,
            max_tokens=4096,
        ),
        description="KoboldAI local provider",
    )
    deepseek: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            timeout=30,
            max_tokens=4096,
        ),
        description="DeepSeek provider",
    )
    mistral: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="mistral-small-latest",
            base_url="https://api.mistral.ai/v1",
            timeout=30,
            max_tokens=4096,
        ),
        description="Mistral AI provider",
    )
    together: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
            base_url="https://api.together.xyz/v1",
            timeout=30,
            max_tokens=4096,
        ),
        description="Together AI provider",
    )
    azure_openai: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="gpt-4o-mini",
            base_url="https://YOUR_RESOURCE.openai.azure.com",
            timeout=30,
            max_tokens=4096,
        ),
        description="Azure OpenAI provider",
        alias="azure-openai",
    )
    alibaba: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="qwen-turbo",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=30,
            max_tokens=4096,
        ),
        description="Alibaba DashScope provider",
    )
    huggingface: ProviderConfig = Field(
        default_factory=lambda: ProviderConfig(
            api_key=SecretStr(""),
            model="Qwen/Qwen2.5-72B-Instruct",
            base_url="https://api-inference.huggingface.co/v1",
            timeout=30,
            max_tokens=4096,
        ),
        description="HuggingFace Inference provider",
    )
    aws: AWSConfig = Field(default_factory=AWSConfig, description="AWS Bedrock provider")
    gcp: GCPConfig = Field(default_factory=GCPConfig, description="GCP Vertex AI provider")

    model_config = ConfigDict(
        extra="allow",
        description="Allow extra providers (e.g. ``opencode``, ``openai``) not explicitly listed.",
    )


# =============================================================================
# ── Speech‑to‑Text (STT) ──
# =============================================================================


class FasterWhisperConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Local faster‑whisper STT configuration."""

    model: Literal["tiny", "base", "small", "medium", "large"] = Field(default="base", description="Whisper model size")


class OpenAIWhisperConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """OpenAI Whisper API STT configuration."""

    api_key: str = Field(default="", description="OpenAI API key")
    model: str = Field(default="whisper-1", description="Whisper model name")


class GroqWhisperConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Groq Whisper API STT configuration."""

    api_key: str = Field(default="", description="Groq API key")
    model: str = Field(default="whisper-large-v3", description="Whisper model name")
    base_url: str = Field(default="https://api.groq.com/openai/v1", description="Groq API base URL")


class WhisperCppConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """whisper.cpp server STT configuration."""

    url: str = Field(default="http://127.0.0.1:8080", description="whisper.cpp server URL")


class DeepgramSTTConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Deepgram STT configuration."""

    api_key: str = Field(default="", description="Deepgram API key")
    model: str = Field(default="nova-2", description="Deepgram STT model name")


class STTConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Speech‑to‑Text engine selection and sub‑configs."""

    engine: Literal["browser", "faster-whisper", "openai-whisper", "groq-whisper", "whispercpp", "deepgram"] = Field(
        default="browser", description="Active STT engine"
    )
    faster_whisper: FasterWhisperConfig = Field(default_factory=FasterWhisperConfig)
    openai_whisper: OpenAIWhisperConfig = Field(default_factory=OpenAIWhisperConfig)
    groq_whisper: GroqWhisperConfig = Field(default_factory=GroqWhisperConfig)
    whispercpp: WhisperCppConfig = Field(default_factory=WhisperCppConfig)
    deepgram: DeepgramSTTConfig = Field(default_factory=DeepgramSTTConfig)


# =============================================================================
# ── Text‑to‑Speech (TTS) ──
# =============================================================================


class OpenAITTSConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """OpenAI TTS API configuration."""

    api_key: str = Field(default="", description="OpenAI API key")
    model: str = Field(default="tts-1", description="TTS model name")
    voice: str = Field(default="alloy", description="TTS voice identifier")
    base_url: str = Field(default="https://api.openai.com/v1", description="OpenAI API base URL")


class ElevenLabsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """ElevenLabs TTS configuration."""

    api_key: str = Field(default="", description="ElevenLabs API key")
    voice_id: str = Field(default="", description="Voice ID")
    model: str = Field(default="eleven_multilingual_v2", description="ElevenLabs model name")


class AllTalkConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """AllTalk TTS server configuration."""

    url: str = Field(default="http://127.0.0.1:7851", description="AllTalk server URL")
    language: str = Field(default="en", description="Language code")
    version: Literal["v1", "v2"] = Field(default="v2", description="AllTalk API version")
    rvc_voice: str = Field(default="", description="RVC voice name")
    rvc_pitch: str = Field(default="0", description="RVC pitch adjustment")


class PiperConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Piper TTS server configuration."""

    url: str = Field(default="http://127.0.0.1:5000", description="Piper server URL")


class CoquiLocalConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Local Coqui TTS configuration."""

    url: str = Field(default="http://127.0.0.1:5002", description="Coqui server URL")
    speaker_id: str = Field(default="", description="Speaker ID")


class KokoroConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Kokoro TTS server configuration."""

    url: str = Field(default="http://127.0.0.1:8880", description="Kokoro server URL")
    voice: str = Field(default="af_heart", description="Voice identifier")


class AzureTTSConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Azure Cognitive Services TTS configuration."""

    api_key: str = Field(default="", description="Azure subscription key")
    region: str = Field(default="eastus", description="Azure region")


class DashscopeTTSConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Alibaba DashScope (CosyVoice) TTS configuration."""

    api_key: str = Field(default="", description="DashScope API key")
    model: str = Field(default="cosyvoice-v1", description="Model name")


class VolcengineTTSConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Volcengine TTS configuration."""

    app_id: str = Field(default="", description="Volcengine app ID")
    access_token: str = Field(default="", description="Access token")
    cluster: str = Field(default="volcano_tts", description="Cluster name")


class DeepgramTTSConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Deepgram TTS configuration."""

    api_key: str = Field(default="", description="Deepgram API key")
    model: str = Field(default="aura-2", description="TTS model name")


class RVCConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Retrieval‑based Voice Conversion (RVC) configuration."""

    url: str = Field(default="http://127.0.0.1:7897", description="RVC server URL")
    f0_up_key: int = Field(default=0, description="Pitch shift in semitones")
    f0_method: str = Field(default="rmvpe", description="F0 extraction method")


class TTSConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Text‑to‑Speech engine selection and sub‑configs."""

    engine: Literal["edge-tts", "openvoice", "elevenlabs", "openai-tts", "speecht5", "alltalk", "piper", "coqui-local", "kokoro"] = Field(
        default="edge-tts", description="Active TTS engine"
    )
    stt_engine: str = Field(default="browser", description="STT engine for voice input")
    openai: OpenAITTSConfig = Field(default_factory=OpenAITTSConfig, description="OpenAI TTS")
    elevenlabs: ElevenLabsConfig = Field(default_factory=ElevenLabsConfig, description="ElevenLabs TTS")
    alltalk: AllTalkConfig = Field(default_factory=AllTalkConfig, description="AllTalk TTS")
    piper: PiperConfig = Field(default_factory=PiperConfig, description="Piper TTS")
    coqui_local: CoquiLocalConfig = Field(default_factory=CoquiLocalConfig, description="Coqui local TTS")
    kokoro: KokoroConfig = Field(default_factory=KokoroConfig, description="Kokoro TTS")
    azure: AzureTTSConfig = Field(default_factory=AzureTTSConfig, description="Azure TTS")
    dashscope: DashscopeTTSConfig = Field(default_factory=DashscopeTTSConfig, description="DashScope TTS")
    volcengine: VolcengineTTSConfig = Field(default_factory=VolcengineTTSConfig, description="Volcengine TTS")
    deepgram: DeepgramTTSConfig = Field(default_factory=DeepgramTTSConfig, description="Deepgram TTS")
    rvc: RVCConfig = Field(default_factory=RVCConfig, description="RVC post‑processing")
    timeout: float = Field(default=60.0, ge=5.0, le=300.0, description="TTS request timeout in seconds")


# =============================================================================
# ── VAD ──
# =============================================================================


class VADConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Voice Activity Detection configuration."""

    mode: Literal[0, 1, 2, 3] = Field(default=2, description="VAD aggressiveness (0‑3)")
    frame_size: int = Field(default=960, ge=160, le=1920, description="VAD frame size in samples")
    energy_threshold: float = Field(default=0.02, ge=0.0, le=1.0, description="Energy threshold for VAD")
    silence_frames: int = Field(default=33, ge=1, description="Consecutive silent frames before end of speech")


# =============================================================================
# ── Wake Word ──
# =============================================================================


class WakeWordConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Wake‑word / hotword detection configuration."""

    enabled: bool = Field(default=False, description="Enable wake‑word detection")
    engine: str = Field(default="openwakeword", description="Wake‑word engine name")
    sensitivity: float = Field(default=0.5, ge=0.0, le=1.0, description="Detection sensitivity")
    model: str = Field(default="hey_amalgam", description="Wake‑word model name")


# =============================================================================
# ── Voice (aggregate) ──
# =============================================================================


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Aggregate voice settings (STT, TTS, VAD, wake‑word)."""

    engine: str = Field(default="edge-tts", description="Active TTS engine (top‑level)")
    lipsync_enabled: bool = Field(default=True, description="Enable lip‑sync (top‑level)")
    stt_engine: str = Field(default="browser", description="Active STT engine (top‑level)")
    vad_mode: int = Field(default=2, ge=0, le=3, description="VAD mode (top‑level)")
    vad_frame_size: int = Field(default=960, ge=160, le=1920, description="VAD frame size (top‑level)")
    vad_energy_threshold: float = Field(default=0.02, ge=0.0, le=1.0, description="VAD energy threshold (top‑level)")
    vad_silence_frames: int = Field(default=33, ge=1, description="VAD silence frames (top‑level)")
    tts_timeout: float = Field(default=60.0, ge=5.0, le=300.0, description="TTS timeout at voice level")

    faster_whisper: FasterWhisperConfig = Field(default_factory=FasterWhisperConfig)
    openai_whisper: OpenAIWhisperConfig = Field(default_factory=OpenAIWhisperConfig)
    openai_tts: OpenAITTSConfig = Field(default_factory=OpenAITTSConfig)
    groq_whisper: GroqWhisperConfig = Field(default_factory=GroqWhisperConfig)
    whispercpp: WhisperCppConfig = Field(default_factory=WhisperCppConfig)
    deepgram_stt: DeepgramSTTConfig = Field(default_factory=DeepgramSTTConfig)
    deepgram_tts: DeepgramTTSConfig = Field(default_factory=DeepgramTTSConfig)
    alltalk: AllTalkConfig = Field(default_factory=AllTalkConfig)
    piper: PiperConfig = Field(default_factory=PiperConfig)
    coqui_local: CoquiLocalConfig = Field(default_factory=CoquiLocalConfig)
    kokoro: KokoroConfig = Field(default_factory=KokoroConfig)
    azure: AzureTTSConfig = Field(default_factory=AzureTTSConfig)
    dashscope: DashscopeTTSConfig = Field(default_factory=DashscopeTTSConfig)
    volcengine: VolcengineTTSConfig = Field(default_factory=VolcengineTTSConfig)
    rvc: RVCConfig = Field(default_factory=RVCConfig)
    elevenlabs: ElevenLabsConfig = Field(default_factory=ElevenLabsConfig)

    # Extra fields present in real settings.json (not in DEFAULTS but widely used)
    preferred_voice_id: str = Field(default="", description="Preferred TTS voice identifier (name or ID)")
    input_enabled: bool = Field(default=True, description="Microphone input enabled")
    output_enabled: bool = Field(default=True, description="Audio output enabled")

    # Backward‑compat alias for code that uses "voice.deepgram" for STT
    deepgram: DeepgramSTTConfig = Field(
        default_factory=DeepgramSTTConfig,
        description="Deepgram STT (alias for deepgram_stt, used by legacy code)",
    )

    @model_validator(mode="after")
    def _sync_deepgram_aliases(self):
        """Keep deepgram and deepgram_stt in sync (N7)."""
        if self.deepgram is not self.deepgram_stt:
            object.__setattr__(self, 'deepgram', self.deepgram_stt)
        return self


# =============================================================================
# ── Avatar ──
# =============================================================================


class AvatarConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """VRM‑based avatar / digital human configuration."""

    enabled: bool = Field(default=True, description="Enable avatar rendering")
    model_path: str = Field(default="", description="Path to VRM model file")
    scale: float = Field(default=1.0, ge=0.1, le=10.0, description="Avatar scale factor")
    emotion_expressiveness: float = Field(default=0.8, ge=0.0, le=1.0, description="Emotion animation intensity")
    idle_animation_enabled: bool = Field(default=True, description="Play idle animations")
    life_state_machine_enabled: bool = Field(default=True, description="Enable life‑state transitions")
    quality: Literal["basic", "standard", "advanced"] = Field(default="standard", description="Rendering quality tier")
    postfx_enabled: bool = Field(default=False, description="Enable post‑processing effects")


# =============================================================================
# ── Shell ──
# =============================================================================


class ShellConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Shell command execution configuration."""

    mode: Literal["safe", "normal", "off"] = Field(default="safe", description="Shell execution mode")
    allowed_prefixes: List[str] = Field(
        default=[
            "echo", "ls", "cat", "pwd", "date",
            "find", "grep", "head", "tail", "wc",
            "mkdir", "cp", "mv", "rm", "touch",
            "curl", "wget",
            "python3", "python",
            "pip", "pip3",
            "whoami", "uname", "notify-send",
            "ps", "top", "htop",
            "df", "du", "free",
            "which", "kill", "pkill",
            "xdotool", "xclip", "wl-paste",
        ],
        description="Shell commands allowed in safe mode",
    )


# =============================================================================
# ── Behavior ──
# =============================================================================


class BehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Agent behavior and autonomy settings."""

    permission_level: Literal["readonly", "confirm", "full"] = Field(
        default="confirm", description="Tool execution permission level"
    )
    companion_enabled: bool = Field(default=False, description="Enable companion (always‑on) mode")
    idle_prompt_frequency_sec: int = Field(default=30, ge=10, le=300, description="Idle prompt interval in seconds")
    auto_summarize_threshold_turns: int = Field(default=40, ge=5, le=200, description="Turns before auto‑summarize")
    thinking_enabled: bool = Field(default=True, description="Show thinking/reasoning")
    tool_approval_mode: Literal["ask", "auto", "allow"] = Field(
        default="ask", description="Tool approval mode"
    )
    sideagent_enabled: bool = Field(default=False, description="Enable side agent memory")
    background_curator_enabled: bool = Field(default=True, description="Background memory curation")
    constitution_compressed: bool = Field(default=False, description="Use compressed constitution for context")


# =============================================================================
# ── Memory ──
# =============================================================================


class MemoryCompactionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Memory compaction / consolidation settings."""

    enabled: bool = Field(default=True, description="Enable memory compaction")
    importance_threshold: float = Field(default=0.3, ge=0.0, le=1.0, description="Minimum importance to retain")
    aggressiveness: float = Field(default=0.5, ge=0.0, le=1.0, description="Compaction aggressiveness")
    frequency_turns: int = Field(default=10, ge=1, le=100, description="Compact every N turns")
    frequency_minutes: int = Field(default=0, ge=0, description="Compact every N minutes (0 = disabled)")
    max_working_memory: int = Field(default=50, ge=5, le=500, description="Max working memory items")


class MemoryStrategiesConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Memory retrieval strategy selections."""

    episodic: str = Field(default="chromadb", description="Episodic memory backend")
    semantic: str = Field(default="bm25", description="Semantic memory backend")
    hybrid: str = Field(default="weighted", description="Hybrid retrieval strategy")
    fts: str = Field(default="sqlite_fts5", description="Full‑text search backend")


class OpenAIEmbeddingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """OpenAI embedding API configuration."""

    api_key: str = Field(default="", description="OpenAI API key for embeddings")
    model: str = Field(default="text-embedding-3-small", description="Embedding model name")


class OllamaEmbeddingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Ollama local embedding configuration."""

    base_url: str = Field(default="http://localhost:11434", description="Ollama server URL")
    model: str = Field(default="nomic-embed-text", description="Embedding model name")


class MemoryEmbeddingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Embedding provider sub‑configs."""

    openai: OpenAIEmbeddingConfig = Field(default_factory=OpenAIEmbeddingConfig)
    ollama: OllamaEmbeddingConfig = Field(default_factory=OllamaEmbeddingConfig)


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Memory and context management configuration."""

    retrieval_k: int = Field(default=3, ge=1, le=20, description="Number of memory items to retrieve")
    context_window: int = Field(default=50, ge=5, le=200, description="Context window size in turns")
    summarize_threshold: int = Field(default=40, ge=5, le=200, description="Turns before summarization")
    summarize_keep: int = Field(default=15, ge=2, le=100, description="Turns to keep after summarization")
    embedding_backend: Literal["provider", "openai", "ollama"] = Field(
        default="provider", description="Embedding backend"
    )
    fact_extraction: bool = Field(default=True, description="Extract facts from conversation")
    fts_cross_session_enabled: bool = Field(default=True, description="Cross‑session full‑text search")
    retention_days: int = Field(default=90, ge=1, le=365, description="Memory retention period in days")
    export_dir: str = Field(default="", description="Memory export directory (default: data/conversations)")

    compaction: MemoryCompactionConfig = Field(default_factory=MemoryCompactionConfig)
    strategies: MemoryStrategiesConfig = Field(default_factory=MemoryStrategiesConfig)
    embedding: MemoryEmbeddingConfig = Field(default_factory=MemoryEmbeddingConfig)


# =============================================================================
# ── Privacy ──
# =============================================================================


class PrivacyConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Privacy and telemetry configuration."""

    metrics_opt_out: bool = Field(default=False, description="Opt out of usage metrics")
    memory_auto_delete_days: int = Field(default=0, ge=0, le=365, description="Auto‑delete memories after N days (0 = never)")
    crash_report_opt_in: bool = Field(default=False, description="Opt in to crash reporting")
    local_only_mode: bool = Field(default=False, description="Run in fully local mode")
    export_on_shutdown: bool = Field(default=False, description="Export data on shutdown")


# =============================================================================
# ── Advanced ──
# =============================================================================


class AdvancedConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Advanced runtime configuration."""

    hot_reload_enabled: bool = Field(default=True, description="Hot‑reload settings on file change")
    parallel_tool_calls: bool = Field(default=True, description="Execute tool calls in parallel")
    max_concurrent_sub_agents: int = Field(default=3, ge=1, le=10, description="Max concurrent sub‑agents")
    llm_router_enabled: bool = Field(default=True, description="Enable LLM request router")
    debug_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="WARNING", description="Debug log level"
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Default temperature")
    max_tokens: int = Field(default=2048, ge=128, le=8192, description="Default max tokens")
    llm_timeout: float = Field(default=120.0, ge=5.0, le=300.0, description="LLM request timeout")
    context_token_limit: int = Field(default=6000, ge=1000, le=32000, description="Context token limit")
    routing_strategy: Literal["single", "router", "fallback"] = Field(
        default="single", description="Provider routing strategy"
    )
    fallback_providers: List[str] = Field(default_factory=list, description="Ordered fallback providers")
    sliding_window_size: int = Field(default=20, ge=5, le=100, description="Sliding window turns")


# =============================================================================
# ── UI ──
# =============================================================================


class UIConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """User interface configuration."""

    theme: Literal["dark", "midnight", "light", "nord"] = Field(default="dark", description="UI theme")
    font_size: int = Field(default=14, ge=10, le=24, description="Font size in pixels")
    language: Literal["en", "zh"] = Field(default="en", description="UI language")
    show_timestamps: bool = Field(default=False, description="Show message timestamps")
    compact_mode: bool = Field(default=False, description="Compact message display")
    accent_color: str = Field(default="#6c5ce7", description="Accent colour hex code")
    voice_input: bool = Field(default=True, description="Enable voice input in UI")
    voice_output: bool = Field(default=True, description="Enable voice output in UI")
    thinking_enabled: bool = Field(default=True, description="Show assistant thinking in UI")


# =============================================================================
# ── MCP ──
# =============================================================================


MCPServerEntry = Dict[str, Any]


class MCPConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """MCP (Model Context Protocol) server configuration.

    Note: The authoritative server defaults live in ``settings.DEFAULTS["mcp"]["servers"]``.
    This model defaults to an empty list since the real data always flows from
    ``Settings.load()`` which merges DEFAULTS first. (C7)
    """

    servers: List[MCPServerEntry] = Field(
        default_factory=list,
        description="MCP server definitions (populated from DEFAULTS by Settings.load)",
    )


# =============================================================================
# ── Vault ──
# =============================================================================


class VaultConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """RAG vault / knowledge base configuration."""

    path: str = Field(default="", description="Vault directory path (default: data/vault)")
    inject_tokens: int = Field(default=200, ge=0, le=1000, description="Max tokens to inject from vault")


# =============================================================================
# ── LLM ──
# =============================================================================


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Raw LLM request tuning (separate from AdvancedConfig for granularity)."""

    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="LLM temperature")
    max_tokens: int = Field(default=2048, ge=128, le=8192, description="Max tokens per response")
    timeout: float = Field(default=120.0, ge=5.0, le=300.0, description="LLM request timeout")
    context_token_limit: int = Field(default=6000, ge=1000, le=32000, description="Context token limit")
    routing_strategy: Literal["single", "router", "fallback"] = Field(
        default="single", description="Provider routing strategy"
    )
    fallback_providers: List[str] = Field(default_factory=list, description="Ordered fallback providers")
    context_strategy: Literal["full", "sliding_window", "summary"] = Field(
        default="full", description="Context window strategy"
    )
    sliding_window_size: int = Field(default=20, ge=5, le=100, description="Sliding window turns")


# =============================================================================
# ── Log ──
# =============================================================================


class LogConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Application logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="WARNING", description="Log level"
    )
    format: str = Field(default="console", description="Log format (console / json)")


# =============================================================================
# ── Telegram ──
# =============================================================================


class TelegramConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Telegram bot integration configuration."""

    token: str = Field(default="", description="Telegram bot token")
    allowed_users: List[Union[int, str]] = Field(default_factory=list, description="Allowed Telegram user IDs (int or string)")
    enabled: bool = Field(default=False, description="Enable Telegram bot")


# =============================================================================
# ── Auth ──
# =============================================================================


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """API authentication configuration."""

    mode: Literal["none", "api_key", "oauth"] = Field(default="none", description="Auth mode")
    api_key: str = Field(default="", description="API key for auth")


# =============================================================================
# ── System Prompt ──
# =============================================================================


class SystemPromptConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """System prompt selection and overrides."""

    active: str = Field(default="default", description="Active system prompt profile")
    additional_instructions: str = Field(default="", description="Extra instructions appended to system prompt")
    max_tokens: int = Field(default=0, ge=0, description="Max tokens for system prompt (0 = unlimited)")


# =============================================================================
# ── Character (settings section) ──
# =============================================================================


class TranslationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Translation service configuration."""

    enabled: bool = Field(default=False, description="Enable translation")
    source_lang: str = Field(default="auto", description="Source language code")
    target_lang: str = Field(default="ZH", description="Target language code")
    base_url: str = Field(default="http://localhost:1188/translate", description="Translation API base URL")


class CompanionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Companion / proactive agent configuration."""

    enabled: bool = Field(default=False, description="Enable companion mode")
    idle_check_delay: int = Field(default=10, ge=1, le=300, description="Delay before idle check (seconds)")
    proactive_interval: int = Field(default=60, ge=10, le=3600, description="Interval between proactive prompts (seconds)")
    time_awareness: bool = Field(default=True, description="Inject time context")
    personality_notes: str = Field(default="", description="Personality override notes")


class CharacterSettings(BaseModel):
    model_config = ConfigDict(extra="allow")
    """Active character selection (settings section, not full character schema)."""

    active: str = Field(default="default", description="Active character ID")
    system_prompt: str = Field(default="", description="Character system prompt override")
    rules: str = Field(default="", description="Character behaviour rules")
    greeting: str = Field(default="", description="Character greeting message")


# =============================================================================
# ── ROOT ──
# =============================================================================


class AppSettings(BaseModel):
    """Complete application settings — every section the application uses.

    This is the top‑level Pydantic model.  Call ``model_dump_flat()`` to get a
    backwards‑compatible dot‑notation dict that the rest of the codebase still
    expects.
    """

    config_version: int = Field(default=1, description="Settings schema version")
    profile: str = Field(
        default="default", description="Active settings profile name"
    )

    # ── Named sections ──
    provider: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    avatar: AvatarConfig = Field(default_factory=AvatarConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    advanced: AdvancedConfig = Field(default_factory=AdvancedConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    vault: VaultConfig = Field(default_factory=VaultConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    character: CharacterSettings = Field(default_factory=CharacterSettings)
    shell: ShellConfig = Field(default_factory=ShellConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    system_prompt: SystemPromptConfig = Field(default_factory=SystemPromptConfig)
    translation: TranslationConfig = Field(default_factory=TranslationConfig)
    companion: CompanionConfig = Field(default_factory=CompanionConfig)

    # ── Wake word lives under voice already, but keep top‑level for flat dumps ──
    wake_word: WakeWordConfig = Field(default_factory=WakeWordConfig)

    model_config = ConfigDict(
        extra="allow",
        description="Allow arbitrary extra fields from settings.json to pass through.",
    )

    def model_dump_flat(self) -> Dict[str, Any]:
        """Convert the nested model to a flat dot‑notation dict.

        This is the backwards‑compatibility bridge so existing code using
        ``settings.get("provider.active")`` continues to work unchanged.

        ``SecretStr`` values are resolved to their plain‑text content so that
        downstream code receives the actual API keys as it did with the old
        flat dict.
        """
        raw = self.model_dump(exclude_none=True, by_alias=True, mode="python")
        resolved = _resolve_secrets(raw)
        return _flatten(resolved)


# =============================================================================
# ── Flat‑dump helper ──
# =============================================================================


def _resolve_secrets(d: Any) -> Any:
    """Recursively walk *d* and replace ``SecretStr`` instances with their plain value."""
    if isinstance(d, dict):
        return {k: _resolve_secrets(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_resolve_secrets(v) for v in d]
    if hasattr(d, "get_secret_value"):  # SecretStr / SecretBytes
        return d.get_secret_value()
    return d


def _flatten(d: Any, prefix: str = "") -> Dict[str, Any]:
    """Recursively flatten *d* into dot‑notation keys.

    Pydantic's ``model_dump()`` output goes through this to produce dicts like::

        {"provider.active": "gemini", "voice.engine": "edge-tts", ...}
    """
    result: Dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                # Recurse; suppress empty dicts
                nested = _flatten(v, key)
                if nested:
                    result.update(nested)
                else:
                    result[key] = v
            elif isinstance(v, list):
                # Keep lists as-is to preserve type (C4 fix)
                result[key] = v
            else:
                result[key] = v
    elif isinstance(d, (list, tuple)):
        # Top‑level list – shouldn't happen for settings, but handle gracefully
        for i, item in enumerate(d):
            result.update(_flatten(item, f"{prefix}.{i}" if prefix else str(i)))
    else:
        result[prefix] = d
    return result
