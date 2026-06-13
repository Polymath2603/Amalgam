import io
import wave
import numpy as np

def numpy_to_wav_bytes(audio_np: np.ndarray, sample_rate: int) -> bytes:
    pcm = (np.clip(audio_np, -1.0, 1.0) * 32767).astype("int16").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def wav_bytes_to_numpy(wav_bytes: bytes) -> tuple:
    """Convert WAV bytes back to (numpy_float32_array, sample_rate)."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        n_frames = wf.getnframes()
        sr = wf.getframerate()
        frames = wf.readframes(n_frames)
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0
    return audio, sr
