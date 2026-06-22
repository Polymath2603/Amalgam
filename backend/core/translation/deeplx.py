"""
DeepLX translation client.

DeepLX is a self-hosted translation API. It runs at
http://localhost:1188/translate by default.

Translation is optional — all errors are logged and the original
text is returned so the conversation is never interrupted.
"""
import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_DEEPLX_URL = "http://localhost:1188/translate"


async def translate_text(
    text: str,
    target_lang: str = "ZH",
    source_lang: str = "auto",
    deeplx_url: str = DEFAULT_DEEPLX_URL,
) -> str:
    """Translate *text* to *target_lang* via DeepLX.

    Args:
        text: Source text to translate.
        target_lang: Target language code (e.g. "ZH", "JA", "FR").
        source_lang: Source language code (e.g. "auto", "EN", "ZH").
        deeplx_url: Full URL of the DeepLX translate endpoint.

    Returns:
        Translated text on success, original *text* on any error.
    """
    if not text or not text.strip():
        return text

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                deeplx_url,
                json={
                    "text": text,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                },
            )
            data = resp.json()
            code = data.get("code")
            # API can return int or string codes
            if str(code) == "200":
                return data.get("data", text)
            logger.warning(
                "DeepLX returned code=%s for target=%s: %s",
                code,
                target_lang,
                text[:80],
            )
            return text
    except httpx.TimeoutException:
        logger.warning("DeepLX request timed out (target=%s)", target_lang)
        return text
    except httpx.RequestError as exc:
        logger.warning("DeepLX request failed: %s", exc)
        return text
    except Exception as exc:
        logger.warning("DeepLX translation error: %s", exc)
        return text
