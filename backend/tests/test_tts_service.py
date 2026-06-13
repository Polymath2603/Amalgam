"""Tests for TTS _make_wav_bytes — pure function, no mocks."""
import io
import wave
import numpy as np
from backend.core.utils.wav import numpy_to_wav_bytes as _make_wav_bytes


class TestMakeWavBytes:
    def test_starts_with_riff(self):
        audio = np.sin(np.linspace(0, 2 * np.pi * 440, 16000)).astype(np.float32)
        result = _make_wav_bytes(audio, 16000)
        assert result[:4] == b"RIFF"

    def test_contains_wave_header(self):
        audio = np.sin(np.linspace(0, 2 * np.pi * 440, 16000)).astype(np.float32)
        result = _make_wav_bytes(audio, 16000)
        assert b"WAVE" in result[:12]

    def test_valid_wav_parseable(self):
        audio = np.sin(np.linspace(0, 2 * np.pi * 440, 8000)).astype(np.float32)
        result = _make_wav_bytes(audio, 16000)
        buf = io.BytesIO(result)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == 8000

    def test_zero_length_audio(self):
        audio = np.array([], dtype=np.float32)
        result = _make_wav_bytes(audio, 16000)
        buf = io.BytesIO(result)
        with wave.open(buf, "rb") as wf:
            assert wf.getnframes() == 0

    def test_loud_signal_no_clipping(self):
        audio = np.ones(1000, dtype=np.float32)
        result = _make_wav_bytes(audio, 16000)
        buf = io.BytesIO(result)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(1000)
            samples = np.frombuffer(frames, dtype=np.int16)
            assert np.all(samples >= -32768)
            assert np.all(samples <= 32767)

    def test_different_sample_rates(self):
        audio = np.sin(np.linspace(0, 2 * np.pi * 440, 4410)).astype(np.float32)
        for sr in [8000, 22050, 44100]:
            result = _make_wav_bytes(audio, sr)
            buf = io.BytesIO(result)
            with wave.open(buf, "rb") as wf:
                assert wf.getframerate() == sr

    def test_silent_audio(self):
        audio = np.zeros(16000, dtype=np.float32)
        result = _make_wav_bytes(audio, 16000)
        buf = io.BytesIO(result)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(16000)
            samples = np.frombuffer(frames, dtype=np.int16)
            assert np.all(samples == 0)
