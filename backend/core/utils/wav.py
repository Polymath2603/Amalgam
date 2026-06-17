# backend/core/utils/wav.py
"""
WAV audio utilities.
Converts numpy float32 audio arrays to WAV bytes for WebSocket streaming.
Imported by: backend/api/ws/tts_service.py
stdlib only — no external dependencies.
"""
import io
import wave
import numpy as np


def numpy_to_wav_bytes(
    audio: np.ndarray,
    sample_rate: int = 22050,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """
    Convert float32 audio array → WAV bytes (with RIFF header).

    audio: float32 array, values in [-1.0, 1.0]. Clipped if out of range.
    sample_rate: Hz. Edge-TTS outputs 24000. ElevenLabs outputs 22050.
    Returns: bytes of a valid WAV file, streamable over WebSocket.
    """
    audio = np.clip(audio.astype(np.float32), -1.0, 1.0)
    pcm = (audio * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def wav_bytes_to_numpy(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    """Inverse of numpy_to_wav_bytes. Returns (float32_array, sample_rate)."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        sr = wf.getframerate()
    pcm = np.frombuffer(frames, dtype=np.int16)
    return pcm.astype(np.float32) / 32767.0, sr
