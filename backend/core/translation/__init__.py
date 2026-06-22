"""Translation module — DeepLX client and exports."""
from backend.core.translation.deeplx import translate_text


class TranslationService:
    """Thin wrapper around translate_text for handler compatibility."""

    def __init__(self, base_url: str = None) -> None:
        import os
        self._url = base_url or os.environ.get("AMALGAM_DEEPLX_URL", "http://localhost:1188/translate")

    async def translate(
        self, text: str, source_lang: str = "auto", target_lang: str = "en"
    ) -> str:
        return await translate_text(
            text, target_lang=target_lang, source_lang=source_lang, deeplx_url=self._url
        )


__all__ = ["translate_text", "TranslationService"]
