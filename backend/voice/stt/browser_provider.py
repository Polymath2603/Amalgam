"""Browser-native SpeechRecognition STT provider.
Transcription is handled entirely client-side via the Web Speech API running
in the browser.  The transcribed text arrives through the WebSocket as a
user_message, bypassing this provider entirely.

This provider exists to satisfy the STTRouter interface.  Its transcribe()
method always returns "" because the actual transcription happens in the
browser, not on the server.  When using the "browser" STT engine, the
BackendWebSocketHandler skips server-side transcription and relies on
client-side results.
"""
from .base import STTProvider


class BrowserSTTProvider(STTProvider):
    def transcribe(self, audio_np) -> str:
        return ""
