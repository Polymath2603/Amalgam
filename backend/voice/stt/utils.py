import numpy as np
import struct


def numpy_to_wav(audio_np: np.ndarray, sr: int = 16000) -> bytes:
    """Convert float32 numpy array to WAV bytes."""
    pcm = (audio_np * 32767).astype("int16").tobytes()
    data_size = len(pcm)
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + data_size, b'WAVE',
        b'fmt ', 16, 1, 1, sr, sr * 2, 2, 16,
        b'data', data_size,
    )
    return header + pcm
