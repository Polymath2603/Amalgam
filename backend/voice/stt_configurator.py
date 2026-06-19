import logging

logger = logging.getLogger(__name__)


def configure_stt_pipeline(pipeline, engine: str, settings) -> None:
    match engine:
        case "openai-whisper":
            key = settings.get("voice.openai_whisper.api_key", "")
            model = settings.get("voice.openai_whisper.model", "whisper-1")
            if key:
                pipeline.configure_openai_stt(key, model)
        case "groq-whisper":
            key = settings.get("voice.groq_whisper.api_key", "")
            model = settings.get("voice.groq_whisper.model", "whisper-large-v3")
            url = settings.get("voice.groq_whisper.base_url", None)
            if key:
                pipeline.configure_groq_stt(key, model, url)
        case "deepgram":
            key = settings.get("voice.deepgram.api_key", "")
            model = settings.get("voice.deepgram.model", "nova-2")
            if key:
                pipeline.configure_deepgram_stt(key, model)
        case "whispercpp":
            url = settings.get("voice.whispercpp.url", None)
            pipeline.configure_whispercpp_stt(url)
        case "faster-whisper":
            logger.debug("faster-whisper is local-only, no additional configuration needed")
        case _:
            logger.warning(f"Unknown STT engine: {engine}")
