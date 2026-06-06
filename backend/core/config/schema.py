from pydantic import BaseModel, Field
from typing import Optional


class VoiceSettings(BaseModel):
    engine: str = "edge-tts"
    stt_engine: str = "faster-whisper"
    vad_mode: int = Field(2, ge=0, le=3)
    vad_frame_size: int = Field(480, ge=160, le=960)
    vad_energy_threshold: float = Field(0.02, ge=0.0, le=1.0)
    vad_silence_frames: int = Field(33, ge=1)


class ProviderSettings(BaseModel):
    active: str = "gemini"


class MemorySettings(BaseModel):
    context_window: int = Field(50, ge=5, le=500)
    summarize_threshold: int = Field(40, ge=10)
    summarize_keep: int = Field(15, ge=5)
    retrieval_k: int = Field(3, ge=1, le=20)
    embedding_backend: str = Field("provider", pattern="^(provider|local|disabled)$")


class AppSettings(BaseModel):
    voice: VoiceSettings = VoiceSettings()
    provider: ProviderSettings = ProviderSettings()
    memory: MemorySettings = MemorySettings()
