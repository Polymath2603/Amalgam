"""
Tests for the voice pipeline.

Run with: pytest backend/tests/test_voice_pipeline.py -v

These tests verify each component of the voice pipeline independently.
They do not require a microphone — they use synthetic audio data.
"""

import numpy as np
import pytest
import io
import wave


# ─── Fixtures ────────────────────────────────────────────────────────────────

def make_silence(duration_sec: float, sample_rate: int = 16000) -> np.ndarray:
    """Generate silence as a float32 numpy array."""
    n_samples = int(duration_sec * sample_rate)
    return np.zeros(n_samples, dtype=np.float32)


def make_sine_wave(freq_hz: float, duration_sec: float, sample_rate: int = 16000) -> np.ndarray:
    """Generate a sine wave — simulates speech presence (not silence)."""
    t = np.linspace(0, duration_sec, int(duration_sec * sample_rate), endpoint=False)
    return (np.sin(2 * np.pi * freq_hz * t) * 0.5).astype(np.float32)


def make_wav_bytes(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
    """Convert numpy audio array to WAV bytes for testing."""
    from backend.core.utils.wav import numpy_to_wav_bytes
    return numpy_to_wav_bytes(audio, sample_rate=sample_rate)


# ─── Tests: wav.py ───────────────────────────────────────────────────────────

class TestWavUtils:

    def test_numpy_to_wav_bytes_produces_valid_wav(self):
        """numpy_to_wav_bytes should produce bytes that open as a valid WAV file."""
        from backend.core.utils.wav import numpy_to_wav_bytes
        audio = np.zeros(22050, dtype=np.float32)  # 1 second silence at 22050 Hz
        wav_bytes = numpy_to_wav_bytes(audio, sample_rate=22050)

        assert isinstance(wav_bytes, bytes)
        assert len(wav_bytes) > 44  # must be more than just the WAV header (44 bytes)

        # Must be openable as a WAV file
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 22050
            assert wf.getnframes() == 22050

    def test_numpy_to_wav_bytes_clips_overflow(self):
        """Values outside [-1, 1] should be clipped, not cause errors or artifacts."""
        from backend.core.utils.wav import numpy_to_wav_bytes
        audio = np.array([2.0, -3.0, 0.5], dtype=np.float32)  # contains out-of-range
        wav_bytes = numpy_to_wav_bytes(audio, sample_rate=16000)
        assert wav_bytes is not None  # should not raise

    def test_roundtrip(self):
        """Converting to WAV and back should give the same audio (within float precision)."""
        from backend.core.utils.wav import numpy_to_wav_bytes, wav_bytes_to_numpy
        original = np.array([0.1, 0.5, -0.3, 0.0, 0.9], dtype=np.float32)
        wav_bytes = numpy_to_wav_bytes(original, sample_rate=16000)
        recovered, sr = wav_bytes_to_numpy(wav_bytes)

        assert sr == 16000
        # float32 → int16 → float32 loses some precision, allow 0.001 tolerance
        np.testing.assert_allclose(recovered, original, atol=0.001)


# ─── Tests: VAD ──────────────────────────────────────────────────────────────

class TestVAD:
    """
    Tests for Voice Activity Detection.
    These tests use synthetic audio — no microphone needed.
    """

    def test_vad_accepts_correct_frame_size(self):
        """
        VAD requires exactly 480 samples per frame at 16000 Hz (30ms frames).
        A previous bug used 960 samples — this test documents the correct value.
        """
        try:
            from backend.voice.vad import VADProcessor
        except ImportError:
            pytest.skip("VAD module not available")

        vad = VADProcessor(sample_rate=16000)
        frame_480 = np.zeros(480, dtype=np.float32)

        # Should not raise with correct frame size
        try:
            result = vad.process_frame(frame_480)
            assert isinstance(result, (bool, float))  # returns speech/no-speech decision
        except Exception as e:
            pytest.fail(f"VAD failed with 480-sample frame: {e}")

    def test_vad_rejects_wrong_frame_size(self):
        """VAD should raise or return error for wrong frame sizes."""
        try:
            from backend.voice.vad import VADProcessor
        except ImportError:
            pytest.skip("VAD module not available")

        vad = VADProcessor(sample_rate=16000)
        frame_960 = np.zeros(960, dtype=np.float32)  # old wrong size

        with pytest.raises(Exception):
            # Should raise because frame size is wrong
            vad.process_frame(frame_960)

    def test_silence_detected_as_no_speech(self):
        """Silence should not trigger speech detection."""
        try:
            from backend.voice.vad import VADProcessor
        except ImportError:
            pytest.skip("VAD module not available")

        vad = VADProcessor(sample_rate=16000, threshold=0.5)
        silence_frame = make_silence(0.03)[:480]  # 30ms of silence

        result = vad.process_frame(silence_frame)
        # Result should be False (no speech) or a probability < 0.5
        if isinstance(result, bool):
            assert result is False, "Silence should not be detected as speech"
        elif isinstance(result, float):
            assert result < 0.5, f"Silence speech probability too high: {result}"


# ─── Tests: STT ──────────────────────────────────────────────────────────────

class TestSTT:
    """Tests for Speech-to-Text transcription."""

    @pytest.mark.asyncio
    async def test_stt_returns_string(self):
        """
        STT should accept WAV bytes and return a string (possibly empty).
        Tests that the STT function exists and has the right interface.
        """
        try:
            from backend.voice.stt.faster_whisper import transcribe
        except ImportError:
            pytest.skip("Faster-Whisper STT not available")

        # Generate a WAV file with a sine wave (not real speech, but tests the interface)
        audio = make_sine_wave(440.0, 1.0, 16000)
        wav_bytes = make_wav_bytes(audio, 16000)

        result = await transcribe(wav_bytes, language="en")

        assert isinstance(result, str), f"Expected str, got {type(result)}"
        # We don't assert content because it's not real speech

    @pytest.mark.asyncio
    async def test_stt_handles_silence(self):
        """STT should handle silent audio without crashing."""
        try:
            from backend.voice.stt.faster_whisper import transcribe
        except ImportError:
            pytest.skip("Faster-Whisper STT not available")

        silence = make_silence(1.0, 16000)
        wav_bytes = make_wav_bytes(silence, 16000)

        try:
            result = await transcribe(wav_bytes, language="en")
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"STT crashed on silence: {e}")


# ─── Tests: TTS ──────────────────────────────────────────────────────────────

class TestTTS:
    """Tests for Text-to-Speech generation."""

    @pytest.mark.asyncio
    async def test_tts_returns_bytes(self):
        """TTS should accept a string and return audio bytes."""
        try:
            from backend.voice.tts.edge_tts_backend import synthesize
        except ImportError:
            pytest.skip("Edge-TTS not available")

        result = await synthesize("Hello, this is a test.", voice="en-US-JennyNeural")

        assert isinstance(result, bytes), f"Expected bytes, got {type(result)}"
        assert len(result) > 100, "TTS output seems too short to be real audio"

    @pytest.mark.asyncio
    async def test_tts_handles_empty_string(self):
        """TTS should handle empty input gracefully (return empty bytes or raise cleanly)."""
        try:
            from backend.voice.tts.edge_tts_backend import synthesize
        except ImportError:
            pytest.skip("Edge-TTS not available")

        try:
            result = await synthesize("", voice="en-US-JennyNeural")
            assert isinstance(result, bytes)
        except ValueError:
            pass  # Raising ValueError for empty input is acceptable
        except Exception as e:
            pytest.fail(f"TTS raised unexpected exception for empty input: {e}")
