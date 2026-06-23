"""
TTS synthesis service — per-connection stream IDs, no global mutable state.
"""
import asyncio
import base64
import os
import logging
from typing import Optional

import numpy as np
from fastapi import WebSocket
from backend.api.deps import tts, settings
from backend.core.utils.wav import numpy_to_wav_bytes
from backend.core.errors import TTSError

logger = logging.getLogger(__name__)


def _translation_enabled() -> bool:
    """Check if translation is enabled in settings."""
    try:
        s = settings()
        return bool(s.get("translation.enabled", False))
    except Exception:
        return False


class OrderedTTSScheduler:
    """Parallel TTS generation with ordered delivery to frontend.

    Sentences are generated concurrently, but audio is delivered to the
    WebSocket in sequence order.  If sentence N+1 finishes before
    sentence N, it is buffered until sentence N has been sent.

    Supports interruption by calling :meth:`cancel` — all pending
    generation tasks are cancelled and the buffer is cleared.
    """

    def __init__(self, translation_service=None):
        self._buffer: dict[int, dict | None] = {}
        self._next_idx: int = 0
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._cancelled: bool = False
        self._translation_service = translation_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        """True when no tasks are pending and buffer is drained."""
        return not self._tasks and not self._buffer

    async def submit(
        self,
        idx: int,
        text: str,
        emotion: str,
        ws: WebSocket,
        stream_id: int,
        stream_ref,
    ) -> None:
        """Submit a sentence for parallel TTS generation.

        Generation runs in a background task.  Audio is delivered as
        soon as all prior sentences have been sent.
        """
        if self._cancelled:
            return
        self._buffer[idx] = None  # placeholder
        task = asyncio.create_task(
            self._generate_and_deliver(idx, text, emotion, ws, stream_id, stream_ref)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def flush(
        self, ws: WebSocket, stream_id: int, stream_ref
    ) -> None:
        """Wait for all pending tasks, then deliver remaining results."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        async with self._lock:
            await self._deliver_ready(ws, stream_id, stream_ref)

    async def cancel(self) -> None:
        """Cancel all pending TTS generation tasks and clear buffer."""
        self._cancelled = True
        for t in list(self._tasks):
            if not t.done():
                t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._buffer.clear()
        self._next_idx = 0

    async def cancel_all(self) -> None:
        """Cancel all pending TTS generation tasks and clear buffer.

        Alias for cancel() — provided for consistent naming across subsystems.
        """
        await self.cancel()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _generate_and_deliver(
        self,
        idx: int,
        text: str,
        emotion: str,
        ws: WebSocket,
        stream_id: int,
        stream_ref,
    ) -> None:
        """Generate TTS audio and store / deliver when ready."""
        if self._cancelled or stream_ref() != stream_id:
            return

        try:
            msg = await self._do_generate(text, emotion, ws, stream_id, stream_ref, idx)
            if msg is None:
                return
            if self._cancelled or stream_ref() != stream_id:
                return

            async with self._lock:
                self._buffer[idx] = msg
                await self._deliver_ready(ws, stream_id, stream_ref)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("TTS generation for sentence %d failed: %s", idx, exc)
            async with self._lock:
                self._buffer[idx] = None
                await self._deliver_ready(ws, stream_id, stream_ref)

    async def _do_generate(
        self,
        text: str,
        emotion: str,
        ws: WebSocket,
        stream_id: int,
        stream_ref,
        sentence_idx: int = 0,
    ) -> dict | None:
        """Synthesize TTS audio and return message dict (no delivery).

        If *translation_service* is set and translation is enabled in
        settings, the text is translated before synthesis.
        """
        if stream_ref() != stream_id:
            return None

        if ws.client_state.value != 1:
            logger.warning("TTS: WebSocket not connected, skipping generation")
            return None

        # Translate if service configured
        if self._translation_service is not None and _translation_enabled():
            try:
                source = settings().get("translation.source_lang", "auto")
                target = settings().get("translation.target_lang", "en")
                text = await self._translation_service.translate(
                    text, source_lang=source, target_lang=target
                )
            except Exception as exc:
                logger.warning(
                    "TTS sentence %d translation failed: %s", sentence_idx, exc
                )

        # Capture settings at the start of generation to avoid stale data
        current_settings = settings()
        char = current_settings.get_active_character()
        ref_audio = None
        if tts().engine == "openvoice":
            ref_audio = char.get("voice_ref") if char else None
            if not ref_audio:
                char_dir = char.get("_dir", "") if char else ""
                if char_dir:
                    for name in ("voice.pth", "voice.wav"):
                        candidate = os.path.join(char_dir, name)
                        if os.path.exists(candidate):
                            ref_audio = candidate
                            break
            if not ref_audio:
                logger.warning("No voice_ref for OpenVoice, skipping TTS")
                return None

        try:
            result = await asyncio.wait_for(
                tts().synthesize(text, ref_audio=ref_audio, emotion=emotion),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            logger.warning("TTS timeout for: %s...", text[:50])
            return None
        except TTSError as exc:
            logger.warning("TTS error: %s", exc)
            return None

        # Unpack result — the underlying engine may return 2 or 3 values
        if isinstance(result, tuple):
            if len(result) == 3:
                wav_np, viseme_schedule, sample_rate = result
            elif len(result) == 2:
                wav_np, sample_rate = result
                viseme_schedule = None
            else:
                logger.warning(
                    "TTS returned unexpected tuple length %d", len(result)
                )
                return None
        else:
            logger.warning("TTS returned unexpected type %s", type(result))
            return None

        if wav_np is None or (isinstance(wav_np, np.ndarray) and wav_np.size == 0):
            logger.warning("TTS returned empty audio")
            return None

        try:
            wav_bytes = numpy_to_wav_bytes(wav_np, sample_rate)
            b64 = base64.b64encode(wav_bytes).decode("utf-8")
        except Exception as exc:
            logger.error("Failed to encode TTS audio: %s", exc)
            return None

        duration = len(wav_np) / sample_rate if sample_rate else 0

        # Use captured settings for lipsync check
        lipsync_enabled = current_settings.get("voice.lipsync_enabled", True)

        return {
            "type": "tts_audio",
            "audio": b64,
            "format": "wav",
            "sample_rate": sample_rate,
            "duration": duration,
            "emotion": emotion,
            "sentence_idx": sentence_idx,
            "viseme_schedule": (viseme_schedule if viseme_schedule else []) if lipsync_enabled else [],
        }

    async def _deliver_ready(
        self, ws: WebSocket, stream_id: int, stream_ref
    ) -> None:
        """Send all buffered sentences whose index is next, in order."""
        while self._next_idx in self._buffer and self._buffer[self._next_idx] is not None:
            msg = self._buffer.pop(self._next_idx)
            sent_idx = self._next_idx
            self._next_idx += 1

            if stream_ref() != stream_id:
                # Stream became stale — re-insert the buffer entry so it can be
                # delivered if the stream reconnects, or remains for debugging.
                self._buffer[sent_idx] = msg
                continue

            if msg is None:
                continue

            try:
                await ws.send_json(msg)
                await ws.send_json(
                    {"type": "tts_finished", "sentence_idx": sent_idx}
                )
            except Exception as exc:
                logger.warning("Failed to deliver TTS audio for idx %d: %s", sent_idx, exc)
                break


async def synthesize_sentence(sentence_text: str, sentence_idx: int, expected_stream_id: int,
                               current_stream_id: int, ws: WebSocket, emotion: str = "neutral",
                               translation_service=None):
    """TTS a single sentence and send audio over WebSocket.

    If *translation_service* is provided and translation is enabled in
    settings, the sentence is translated before synthesis.
    """
    try:
        if expected_stream_id != current_stream_id:
            logger.debug(f"TTS sentence {sentence_idx}: skipped (stale stream)")
            return

        # Guard: bail out if WS is already closed
        if ws.client_state.value != 1:  # 1 = CONNECTED
            logger.warning(f"TTS sentence {sentence_idx}: WebSocket not connected, skipping")
            return

        # Translate if service configured
        orig_text = None
        if translation_service is not None and _translation_enabled():
            try:
                source = settings().get("translation.source_lang", "auto")
                target = settings().get("translation.target_lang", "en")
                sentence_text = await translation_service.translate(sentence_text, source_lang=source, target_lang=target)
            except Exception as e:
                logger.warning("TTS sentence %d translation failed: %s", sentence_idx, e)

        char = settings().get_active_character()
        ref_audio = None
        if tts().engine == "openvoice":
            ref_audio = char.get("voice_ref") if char else None
            if not ref_audio:
                char_dir = char.get("_dir", "") if char else ""
                if char_dir:
                    for name in ("voice.pth", "voice.wav"):
                        candidate = os.path.join(char_dir, name)
                        if os.path.exists(candidate):
                            ref_audio = candidate
                            break
            if not ref_audio:
                logger.warning("No voice_ref for OpenVoice, skipping TTS")
                return

        result = await asyncio.wait_for(
            tts().synthesize(sentence_text, ref_audio=ref_audio, emotion=emotion),
            timeout=60.0
        )
        # Safe tuple unpack — engine may return 2 or 3 values
        if isinstance(result, tuple):
            if len(result) == 3:
                audio_np, viseme_schedule, sr = result
            elif len(result) == 2:
                audio_np, sr = result
                viseme_schedule = None
            else:
                logger.warning("TTS returned unexpected tuple length %d in synthesize_sentence", len(result))
                return
        else:
            logger.warning("TTS returned unexpected type %s in synthesize_sentence", type(result))
            return
        logger.debug(f"TTS sentence {sentence_idx}: {len(audio_np)} samples, sr={sr}, visemes={len(viseme_schedule) if viseme_schedule else 0}")
        if len(audio_np) > 0:
            if expected_stream_id != current_stream_id:
                logger.debug(f"TTS sentence {sentence_idx}: skipped (stale stream before send)")
                return
            wav_bytes = numpy_to_wav_bytes(audio_np, sr)
            b64_audio = base64.b64encode(wav_bytes).decode()
            duration = len(audio_np) / sr
            lipsync_enabled = settings().get("voice.lipsync_enabled", True)
            msg = {
                "type": "tts_audio",
                "audio": b64_audio,
                "format": "wav",
                "duration": round(duration, 2),
                "sentence_idx": sentence_idx,
                "emotion": emotion,
            }
            if viseme_schedule and lipsync_enabled:
                msg["viseme_schedule"] = viseme_schedule
            await ws.send_json(msg)
            logger.debug(f"TTS sentence {sentence_idx}: sent {duration:.2f}s audio (emotion={emotion})")
        else:
            logger.warning(f"TTS sentence {sentence_idx}: empty audio")
    except asyncio.TimeoutError:
        logger.error(f"TTS sentence {sentence_idx}: timed out after 60s")
        try:
            if ws.client_state.value == 1:
                await ws.send_json({"type": "tts_error", "message": "TTS synthesis timed out", "sentence_idx": sentence_idx})
        except Exception:
            pass
    except Exception as tts_err:
        logger.error(f"TTS error for sentence {sentence_idx}: {type(tts_err).__name__}: {tts_err}")
        try:
            if ws.client_state.value == 1:
                await ws.send_json({"type": "tts_error", "message": "TTS synthesis failed", "sentence_idx": sentence_idx})
        except Exception:
            pass


async def synthesize_now(text: str, ws: WebSocket, emotion: str = "neutral"):
    """Synthesize TTS for text and send audio directly (used by speak button)."""
    try:
        # Guard: bail out if WS is already closed
        if ws.client_state.value != 1:  # 1 = CONNECTED
            logger.warning("Speak TTS: WebSocket not connected, skipping")
            return

        char = settings().get_active_character()
        ref_audio = None
        if tts().engine == "openvoice":
            ref_audio = char.get("voice_ref") if char else None
            if not ref_audio:
                char_dir = char.get("_dir", "") if char else ""
                if char_dir:
                    for name in ("voice.pth", "voice.wav"):
                        candidate = os.path.join(char_dir, name)
                        if os.path.exists(candidate):
                            ref_audio = candidate
                            break
            if not ref_audio:
                logger.warning("No voice_ref for OpenVoice, skipping speak")
                return
        result = await asyncio.wait_for(tts().synthesize(text, ref_audio=ref_audio, emotion=emotion), timeout=60.0)
        # Safe tuple unpack — engine may return 2 or 3 values
        if isinstance(result, tuple):
            if len(result) == 3:
                audio_np, viseme_schedule, sr = result
            elif len(result) == 2:
                audio_np, sr = result
                viseme_schedule = None
            else:
                logger.warning("TTS returned unexpected tuple length %d in synthesize_now", len(result))
                return
        else:
            logger.warning("TTS returned unexpected type %s in synthesize_now", type(result))
            return
        if len(audio_np) > 0:
            wav_bytes = numpy_to_wav_bytes(audio_np, sr)
            b64_audio = base64.b64encode(wav_bytes).decode()
            duration = len(audio_np) / sr
            lipsync_enabled = settings().get("voice.lipsync_enabled", True)
            msg = {
                "type": "tts_audio", "audio": b64_audio, "format": "wav",
                "duration": round(duration, 2), "sentence_idx": 0, "emotion": emotion,
            }
            if viseme_schedule and lipsync_enabled:
                msg["viseme_schedule"] = viseme_schedule
            await ws.send_json(msg)
            logger.debug(f"Speak TTS: sent {duration:.2f}s audio")
        else:
            logger.warning("Speak TTS: empty audio")
    except asyncio.TimeoutError:
        logger.error("Speak TTS: timed out")
        try:
            if ws.client_state.value == 1:
                await ws.send_json({"type": "tts_error", "message": "TTS speak timed out"})
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Speak TTS error: {e}")
        try:
            if ws.client_state.value == 1:
                await ws.send_json({"type": "tts_error", "message": "TTS speak failed"})
        except Exception:
            pass
