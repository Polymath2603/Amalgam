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
