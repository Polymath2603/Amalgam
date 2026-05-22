"""Browser-native SpeechRecognition STT provider.
Transcription is handled entirely client-side via the Web Speech API.
This provider exists to satisfy the STTRouter interface; the actual
transcription flows through the WebSocket as a user_message.
"""
from .base import STTProvider 


class BrowserSTTProvider (STTProvider ):
    def transcribe (self ,audio_np )->str :
        return ""
