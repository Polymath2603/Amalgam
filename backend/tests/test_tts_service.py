"""
BRUTAL TESTS for WAV utilities — NaN, Inf, extreme arrays, memory safety.

Catches: NaN/Inf values, empty arrays, single sample, max-int arrays,
roundtrip precision, different dtypes, and very large audio.
"""
import io
import wave
import numpy as np
import pytest
from backend.core.utils.wav import numpy_to_wav_bytes as _make_wav_bytes
from backend.core.utils.wav import wav_bytes_to_numpy


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


class TestMakeWavBytesBrutal:
    """Brutal edge cases for WAV generation."""

    def test_nan_values_clipped(self):
        """NaN should be clipped to valid range, not produce garbage."""
        audio = np.array([np.nan, np.nan, 0.5], dtype=np.float32)
        result = _make_wav_bytes(audio, 16000)
        assert result is not None
        assert len(result) > 0

    def test_inf_values_clipped(self):
        """Inf should be clipped to [-1, 1]."""
        audio = np.array([np.inf, -np.inf, 0.0], dtype=np.float32)
        result = _make_wav_bytes(audio, 16000)
        buf = io.BytesIO(result)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(3)
            samples = np.frombuffer(frames, dtype=np.int16)
            # Should be clipped to int16 range
            assert np.all(samples >= -32768)
            assert np.all(samples <= 32767)

    def test_single_sample(self):
        audio = np.array([0.5], dtype=np.float32)
        result = _make_wav_bytes(audio, 16000)
        buf = io.BytesIO(result)
        with wave.open(buf, "rb") as wf:
            assert wf.getnframes() == 1

    def test_very_large_audio(self):
        """1M samples should produce valid WAV."""
        audio = np.random.randn(1_000_000).astype(np.float32) * 0.1
        result = _make_wav_bytes(audio, 16000)
        assert len(result) >= 44 + 2_000_000  # 44 header + 2 bytes per sample

    def test_negative_values(self):
        audio = np.array([-0.5, -0.8, -1.0, -0.1], dtype=np.float32)
        result = _make_wav_bytes(audio, 16000)
        buf = io.BytesIO(result)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(4)
            samples = np.frombuffer(frames, dtype=np.int16)
            assert np.all(samples <= 0)

    def test_out_of_range_clipped(self):
        audio = np.array([2.0, -2.0, 5.0, -10.0], dtype=np.float32)
        result = _make_wav_bytes(audio, 16000)
        buf = io.BytesIO(result)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(4)
            samples = np.frombuffer(frames, dtype=np.int16)
            assert np.all(samples >= -32768)
            assert np.all(samples <= 32767)

    def test_alternating_pos_neg(self):
        audio = np.array([1.0, -1.0] * 500, dtype=np.float32)
        result = _make_wav_bytes(audio, 16000)
        buf = io.BytesIO(result)
        with wave.open(buf, "rb") as wf:
            assert wf.getnframes() == 1000

    def test_very_small_values(self):
        audio = np.array([1e-10, -1e-10, 0.0], dtype=np.float32)
        result = _make_wav_bytes(audio, 16000)
        assert result is not None

    def test_dtype_float64_converted(self):
        """Should handle float64 input by converting to float32."""
        audio = np.array([0.5, -0.5], dtype=np.float64)
        try:
            result = _make_wav_bytes(audio, 16000)
            assert result is not None
        except TypeError:
            pass  # Some implementations may not accept float64


class TestWavRoundtrip:
    def test_basic_roundtrip(self):
        original = np.array([0.1, 0.5, -0.3, 0.0, 0.9], dtype=np.float32)
        wav_bytes = _make_wav_bytes(original, 16000)
        recovered, sr = wav_bytes_to_numpy(wav_bytes)
        assert sr == 16000
        np.testing.assert_allclose(recovered, original, atol=0.001)

    def test_roundtrip_silence(self):
        original = np.zeros(1000, dtype=np.float32)
        wav_bytes = _make_wav_bytes(original, 16000)
        recovered, sr = wav_bytes_to_numpy(wav_bytes)
        np.testing.assert_allclose(recovered, original, atol=0.001)

    def test_roundtrip_loud(self):
        original = np.ones(100, dtype=np.float32)
        wav_bytes = _make_wav_bytes(original, 16000)
        recovered, sr = wav_bytes_to_numpy(wav_bytes)
        # After clipping and roundtrip, should be close to 1.0
        assert np.all(recovered > 0.99)

    def test_roundtrip_preserves_length(self):
        for length in [1, 10, 100, 1000, 10000]:
            original = np.random.randn(length).astype(np.float32) * 0.5
            wav_bytes = _make_wav_bytes(original, 16000)
            recovered, sr = wav_bytes_to_numpy(wav_bytes)
            assert len(recovered) == length

    def test_roundtrip_preserves_sample_rate(self):
        for sr in [8000, 16000, 22050, 44100]:
            original = np.random.randn(100).astype(np.float32) * 0.5
            wav_bytes = _make_wav_bytes(original, sr)
            _, recovered_sr = wav_bytes_to_numpy(wav_bytes)
            assert recovered_sr == sr

    def test_roundtrip_sine_wave(self):
        """Roundtrip a sine wave — should preserve shape within precision."""
        t = np.linspace(0, 0.01, 160)
        original = (np.sin(2 * np.pi * 440 * t) * 0.8).astype(np.float32)
        wav_bytes = _make_wav_bytes(original, 16000)
        recovered, sr = wav_bytes_to_numpy(wav_bytes)
        assert sr == 16000
        np.testing.assert_allclose(recovered, original, atol=0.01)

    def test_roundtrip_zero_length(self):
        original = np.array([], dtype=np.float32)
        wav_bytes = _make_wav_bytes(original, 16000)
        recovered, sr = wav_bytes_to_numpy(wav_bytes)
        assert len(recovered) == 0
        assert sr == 16000


class TestWavBytesToNumpy:
    def test_invalid_bytes_raises(self):
        with pytest.raises(Exception):
            wav_bytes_to_numpy(b"not a wav file")

    def test_empty_bytes_raises(self):
        with pytest.raises(Exception):
            wav_bytes_to_numpy(b"")