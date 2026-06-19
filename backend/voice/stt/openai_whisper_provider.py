"""OpenAI Whisper API STT provider — cloud-based alternative to faster-whisper."""
import logging
import numpy as np
import httpx

from .base import STTProvider
from .utils import numpy_to_wav

logger = logging.getLogger(__name__)


class OpenAIWhisperProvider(STTProvider):
    """STT via OpenAI Whisper API. Requires API key."""

    def __init__(self, api_key="", model="whisper-1"):
        super().__init__()
        self._api_key = api_key
        self._model = model

    def configure(self, api_key: str, model: str = "whisper-1"):
        self._api_key = api_key
        self._model = model

    def transcribe(self, audio_np: np.ndarray) -> str:
        """Transcribe 16kHz float32 numpy array via OpenAI Whisper API."""
        if not self._api_key:
            logger.warning("OpenAI Whisper API key not set")
            return ""

        wav_bytes = numpy_to_wav(audio_np)
        try:
            resp = httpx.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={"model": self._model, "response_format": "text"},
                timeout=120,
            )
            if resp.status_code == 200:
                text = resp.text.strip()
                logger.debug(f"OpenAI Whisper STT: {text}")
                return text
            else:
                logger.error(f"OpenAI Whisper API error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"OpenAI Whisper STT error: {e}")
        return ""
