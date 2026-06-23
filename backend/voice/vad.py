import numpy as np
import logging
import torch

logger = logging.getLogger(__name__)


class SileroVAD:
    def __init__(self, threshold: float = 0.5):
        self._model = None
        self._threshold = threshold
        self._sample_rate = 16000

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            self._model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False,
            )
            self._model.eval()
        except Exception as e:
            logger.warning("SileroVAD load failed, falling back to WebRTC: %s", e)
            raise

    def process(self, audio_bytes: bytes) -> bool:
        self._ensure_model()
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        tensor = torch.from_numpy(samples).unsqueeze(0)
        with torch.no_grad():
            confidence = self._model(tensor, self._sample_rate).item()
        return confidence >= self._threshold


class VAD:
    def __init__(self, mode: int = 2):
        self._silero: SileroVAD | None = None
        self._webrtc = None
        self._mode = mode
        try:
            self._silero = SileroVAD()
        except Exception:
            import webrtcvad
            self._webrtc = webrtcvad.Vad()
            self._webrtc.set_mode(mode)

    def process(self, audio_bytes: bytes) -> bool:
        if self._silero:
            try:
                return self._silero.process(audio_bytes)
            except Exception as e:
                logger.debug("SileroVAD failed, falling back to WebRTC: %s", e)
                self._silero = None
        if self._webrtc:
            try:
                return self._webrtc.is_speech(audio_bytes, 16000)
            except Exception as e:
                logger.debug("WebRTC VAD error: %s", e)
                self._webrtc = None
        # Both VAD methods have failed
        logger.warning("Both SileroVAD and WebRTC VAD have failed — returning False (no speech)")
        return False
