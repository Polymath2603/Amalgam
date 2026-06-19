"""Deepgram STT provider — Deepgram API."""
import json
import logging
import numpy as np
import httpx

from .base import STTProvider
from .utils import numpy_to_wav

logger = logging.getLogger(__name__)


class DeepgramSTTProvider(STTProvider):
    def __init__(self):
        super().__init__()
        self._api_key = ""
        self._model = "nova-2"
        self._base_url = "https://api.deepgram.com/v1"

    def configure(self, api_key: str, model: str = "nova-2"):
        self._api_key = api_key
        self._model = model

    def transcribe(self, audio_np: np.ndarray) -> str:
        if not self._api_key:
            logger.warning("Deepgram API key not set")
            return ""

        wav_bytes = numpy_to_wav(audio_np)
        url = f"{self._base_url.rstrip('/')}/listen?model={self._model}&punctuate=true"
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "audio/wav",
        }

        try:
            resp = httpx.post(url, content=wav_bytes, headers=headers, timeout=120)
            if resp.status_code == 200:
                result = resp.json()
                text = result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "").strip()
                logger.debug(f"Deepgram STT: {text}")
                return text
            else:
                logger.error(f"Deepgram STT error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Deepgram STT error: {e}")
        return ""
