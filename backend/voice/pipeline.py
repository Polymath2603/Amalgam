"""
Formal state machine for the voice pipeline.

States: IDLE, LISTENING, PROCESSING, SPEAKING, INTERRUPTED
Transitions: explicit with guards. Illegal transitions raise VoiceStateError.

Events emitted:
  - voice.state.change (via EventBus)
  - voice.interrupt (when user barges in)

Usage:
    sm = VoiceStateMachine(on_state_change=my_callback)
    await sm.transition(VoiceState.LISTENING)   # IDLE -> LISTENING
    await sm.transition(VoiceState.PROCESSING)  # LISTENING -> PROCESSING
    print(sm.state)  # VoiceState.PROCESSING
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from enum import Enum, auto
from typing import Callable, Optional

import numpy as np

from backend.core.events import get_bus, Events
from backend.voice.stt.router import STTRouter

logger = logging.getLogger(__name__)


# ── State Enum ──────────────────────────────────────────────────────────

class VoiceState(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()
    INTERRUPTED = auto()


# ── Legal transition table ──────────────────────────────────────────────
# Maps (from_state, to_state) -> human-readable reason
_LEGAL_TRANSITIONS: dict[tuple[VoiceState, VoiceState], str] = {
    (VoiceState.IDLE, VoiceState.LISTENING): "VAD speech start",
    (VoiceState.LISTENING, VoiceState.IDLE): "VAD timeout",
    (VoiceState.LISTENING, VoiceState.PROCESSING): "VAD end, utterance complete",
    (VoiceState.PROCESSING, VoiceState.SPEAKING): "TTS response ready",
    (VoiceState.PROCESSING, VoiceState.IDLE): "error or empty response",
    (VoiceState.SPEAKING, VoiceState.IDLE): "TTS playback complete",
    (VoiceState.SPEAKING, VoiceState.INTERRUPTED): "VAD barge-in",
    (VoiceState.INTERRUPTED, VoiceState.LISTENING): "start listening to interruption",
    (VoiceState.INTERRUPTED, VoiceState.IDLE): "timeout or forced stop",
}

# Forced reset: any state -> IDLE is always allowed
_FORCED_RESET = VoiceState.IDLE


class VoiceStateError(ValueError):
    """Raised on illegal state transitions."""
    pass


# ── State Machine ───────────────────────────────────────────────────────

class VoiceStateMachine:
    """
    Formal voice pipeline state machine.

    Both async (transition, reset) and synchronous (transition_sync, reset_sync)
    APIs are provided so the machine can be driven from async code or from
    background threads (e.g. the listen_loop).

    Events are emitted via the global EventBus on every transition.
    An optional on_state_change callback is invoked synchronously.
    """

    def __init__(self, on_state_change: Optional[Callable] = None):
        self._state: VoiceState = VoiceState.IDLE
        self._on_state_change = on_state_change
        self._bus = get_bus()

    # ── Properties ────────────────────────────────────────────────────

    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def state_name(self) -> str:
        return self._state.name.lower()

    def is_idle(self) -> bool:
        return self._state == VoiceState.IDLE

    def is_listening(self) -> bool:
        return self._state == VoiceState.LISTENING

    def is_speaking(self) -> bool:
        return self._state == VoiceState.SPEAKING

    def is_processing(self) -> bool:
        return self._state == VoiceState.PROCESSING

    def is_interrupted(self) -> bool:
        return self._state == VoiceState.INTERRUPTED

    # ── Async API (for async callers) ─────────────────────────────────

    async def transition(self, target: VoiceState) -> None:
        """Attempt a state transition. Raises VoiceStateError if illegal.

        Safe to call from async contexts only.  For threads see
        ``transition_sync``.
        """
        from_state = self._state
        if target is _FORCED_RESET:
            await self._apply(from_state, target, "forced reset")
            return

        key = (from_state, target)
        if key not in _LEGAL_TRANSITIONS:
            raise VoiceStateError(
                f"Illegal transition: {from_state.name} \u2192 {target.name}. "
                f"Allowed from {from_state.name}: "
                f"{[t.name for f, t in _LEGAL_TRANSITIONS if f == from_state]}"
            )

        reason = _LEGAL_TRANSITIONS[key]
        await self._apply(from_state, target, reason)

    async def reset(self) -> None:
        """Forcefully reset to IDLE from any state."""
        if self._state != VoiceState.IDLE:
            await self._apply(self._state, VoiceState.IDLE, "forced reset")

    # ── Synchronous API (for background threads) ──────────────────────

    def transition_sync(self, target: VoiceState) -> None:
        """Synchronous version of ``transition``.

        Intended for use from the listen_loop (which runs in a thread).
        EventBus async handlers will *not* be scheduled, but the state
        change and any sync handlers still fire.
        """
        from_state = self._state
        if target is _FORCED_RESET:
            self._apply_sync(from_state, target, "forced reset")
            return

        key = (from_state, target)
        if key not in _LEGAL_TRANSITIONS:
            raise VoiceStateError(
                f"Illegal transition: {from_state.name} \u2192 {target.name}. "
                f"Allowed from {from_state.name}: "
                f"{[t.name for f, t in _LEGAL_TRANSITIONS if f == from_state]}"
            )

        reason = _LEGAL_TRANSITIONS[key]
        self._apply_sync(from_state, target, reason)

    def reset_sync(self) -> None:
        """Synchronous version of ``reset``."""
        if self._state != VoiceState.IDLE:
            self._apply_sync(self._state, VoiceState.IDLE, "forced reset")

    # ── Internal helpers ──────────────────────────────────────────────

    async def _apply(self, from_state: VoiceState, to_state: VoiceState, reason: str) -> None:
        """Async transition application — delegates to _apply_sync."""
        self._apply_sync(from_state, to_state, reason)

    def _apply_sync(self, from_state: VoiceState, to_state: VoiceState, reason: str) -> None:
        """Core transition logic — synchronous so it is safe from threads."""
        old = self._state
        self._state = to_state

        logger.debug(f"Voice state: {from_state.name} \u2192 {to_state.name} ({reason})")

        # Emit via event bus (sync handlers fire immediately; async handlers
        # are scheduled via create_task when called from an async context)
        self._bus.emit(
            Events.VOICE_STATE_CHANGE,
            from_state=from_state.name.lower(),
            to_state=to_state.name.lower(),
            reason=reason,
        )

        # Emit interrupt event for SPEAKING -> INTERRUPTED
        if from_state == VoiceState.SPEAKING and to_state == VoiceState.INTERRUPTED:
            self._bus.emit(
                Events.VOICE_INTERRUPT,
                from_state=from_state.name.lower(),
                reason=reason,
            )

        # Callback
        if self._on_state_change:
            try:
                self._on_state_change(old, to_state)
            except Exception as e:
                logger.warning(f"State change callback failed: {e}")

    def __repr__(self) -> str:
        return f"<VoiceStateMachine: {self._state.name}>"


# ── Voice Pipeline ──────────────────────────────────────────────────────

class VoicePipeline:
    """
    Voice pipeline with formal state machine.

    Replaces the old ad-hoc boolean flags with a proper VoiceStateMachine.

    Usage:
        pipeline = VoicePipeline(agent_callback=fn, on_speech_start=fn)
        loop.run_in_executor(None, pipeline.listen_loop)

        # From async context:
        await pipeline.start_listening()
        await pipeline.stop_listening()
        await pipeline.start_speaking()
        await pipeline.stop_speaking()
        await pipeline.interrupt()
    """

    def __init__(
        self,
        agent_callback: Optional[Callable] = None,
        stt_engine: str = "browser",
        settings: Optional[dict] = None,
        on_speech_start: Optional[Callable] = None,
        on_state_change: Optional[Callable] = None,
    ):
        self.agent_callback = agent_callback
        self.on_speech_start = on_speech_start

        # State machine (replaces ad-hoc bools)
        self.sm = VoiceStateMachine(on_state_change=on_state_change)
        self._bus = get_bus()

        # Internal state
        self._stop_event = threading.Event()
        self._vad = None
        self._stt = STTRouter(engine=stt_engine)
        self._stt_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="stt"
        )
        self._stream = None
        self._settings = settings or {}
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Convenience properties (delegate to state machine) ──────────────

    @property
    def is_listening(self) -> bool:
        return self.sm.is_listening()

    @property
    def is_speaking(self) -> bool:
        return self.sm.is_speaking()

    @property
    def is_idle(self) -> bool:
        return self.sm.is_idle()

    @property
    def state(self) -> VoiceState:
        return self.sm.state

    # ── STT configuration helpers ──────────────────────────────────────

    def configure_openai_stt(self, api_key: str, model: str = "whisper-1"):
        self._stt.configure_openai(api_key, model)

    def configure_groq_stt(self, api_key: str, model: str = "whisper-large-v3", base_url: str = None):
        self._stt.configure_groq(api_key, model, base_url)

    def configure_whispercpp_stt(self, url: str = None):
        self._stt.configure_whispercpp(url)

    def configure_deepgram_stt(self, api_key: str, model: str = "nova-2"):
        self._stt.configure_deepgram(api_key, model)

    def _ensure_models(self):
        if self._vad is None:
            from backend.voice.vad import VAD
            vad_mode = self._settings.get("voice.vad_mode", 2)
            self._vad = VAD(mode=vad_mode)

    def _on_stt_done(self, future):
        try:
            result = future.result()
            if result is not None and result.strip() and self.agent_callback:
                self.agent_callback(result)
        except concurrent.futures.CancelledError:
            pass
        except Exception as e:
            logger.error(f"STT transcription failed: {e}")

    # ── Listen loop (runs in background thread) ────────────────────────

    def listen_loop(self):
        """Blocking listen loop for background thread. Monitors mic via sounddevice."""
        try:
            import queue

            import sounddevice as sd
        except ImportError:
            logger.warning("sounddevice or queue not installed. Voice input unavailable.")
            return

        self._ensure_models()
        self._stop_event.clear()

        # Capture the running event loop for bridging sync -> async
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._main_loop = None

        logger.debug(f"VoicePipeline: Listening for speech (STT: {self._stt.engine})...")

        audio_q = queue.Queue()

        def audio_callback(indata, frames, time, status):
            if status:
                logger.warning(f"Audio input status: {status}")
            audio_q.put(bytes(indata))

        self._stream = sd.RawInputStream(
            samplerate=16000,
            blocksize=480,
            dtype="int16",
            channels=1,
            callback=audio_callback,
        )

        # Audio buffering state (local to this loop, not the pipeline's state machine)
        recording = bytearray()
        silence_frames = 0
        frame_size = self._settings.get("voice.vad_frame_size", 480)
        energy_threshold = self._settings.get("voice.vad_energy_threshold", 0.02)
        max_silence_frames = self._settings.get("voice.vad_silence_frames", 33)

        # Reset state machine to IDLE at start
        self.sm.reset_sync()

        try:
            with self._stream:
                while not self._stop_event.is_set():
                    try:
                        chunk = audio_q.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    for i in range(0, len(chunk), frame_size):
                        frame = chunk[i : i + frame_size]
                        if len(frame) < frame_size:
                            continue

                        is_speech = self._vad.process(frame)
                        samples = (
                            np.frombuffer(frame, dtype=np.int16).astype(np.float32)
                            / 32768.0
                        )
                        energy = np.sqrt(np.mean(samples**2))
                        speech_detected = is_speech or (energy > energy_threshold)

                        if speech_detected:
                            if not self.sm.is_listening():
                                # VAD speech start: IDLE -> LISTENING or SPEAKING -> INTERRUPTED
                                if self.sm.is_speaking():
                                    # User barged in during TTS playback
                                    self.sm.transition_sync(VoiceState.INTERRUPTED)
                                    self.sm.transition_sync(VoiceState.LISTENING)
                                else:
                                    # Normal start of speech from IDLE
                                    try:
                                        self.sm.transition_sync(VoiceState.LISTENING)
                                    except VoiceStateError:
                                        # Already listening or in another valid state — continue
                                        pass

                                recording = bytearray()
                                silence_frames = 0
                                logger.debug("VoicePipeline: Speech detected")

                                # Fire the on_speech_start callback
                                if self.on_speech_start:
                                    try:
                                        self.on_speech_start()
                                    except Exception as e:
                                        logger.error(
                                            f"VoicePipeline: on_speech_start error: {e}"
                                        )

                            recording.extend(frame)
                            silence_frames = 0

                        elif self.sm.is_listening():
                            # Silence during recording — extend and check for timeout
                            recording.extend(frame)
                            silence_frames += 1

                            if silence_frames > max_silence_frames:
                                # VAD end — utterance complete
                                self.sm.transition_sync(VoiceState.PROCESSING)

                                audio_data = (
                                    np.frombuffer(bytes(recording), dtype=np.int16)
                                    .astype(np.float32)
                                    / 32768.0
                                )
                                if len(audio_data) > 8000:
                                    logger.debug(
                                        f"VoicePipeline: Transcribing {len(audio_data)/16000:.1f}s of audio..."
                                    )
                                    future = self._stt_executor.submit(
                                        self._stt.transcribe, audio_data
                                    )
                                    future.add_done_callback(self._on_stt_done)
                                else:
                                    # Audio too short — return to IDLE
                                    self.sm.transition_sync(VoiceState.IDLE)

                                recording = bytearray()
                                silence_frames = 0

        except Exception as e:
            logger.error(f"VoicePipeline error: {e}")
        finally:
            # Ensure we're back to IDLE
            self.sm.reset_sync()
            logger.debug("VoicePipeline: Stopped")
            self._main_loop = None

    # ── Pipeline control (state machine transitions) ────────────────────

    async def start_listening(self) -> None:
        """IDLE -> LISTENING: VAD detected speech start."""
        await self.sm.transition(VoiceState.LISTENING)

    async def cancel_listening(self) -> None:
        """LISTENING -> IDLE: VAD timeout / silence too long."""
        await self.sm.transition(VoiceState.IDLE)

    async def start_speaking(self) -> None:
        """PROCESSING -> SPEAKING: TTS response ready."""
        await self.sm.transition(VoiceState.SPEAKING)

    async def stop_speaking(self) -> None:
        """SPEAKING -> IDLE: TTS playback complete."""
        await self.sm.transition(VoiceState.IDLE)

    async def start_interruption_listening(self) -> None:
        """INTERRUPTED -> LISTENING: start listening to interruption."""
        await self.sm.transition(VoiceState.LISTENING)

    async def reset(self) -> None:
        """Any -> IDLE: forced reset."""
        await self.sm.reset()

    # ── Sync methods (backward compat, called from threads) ────────────

    def interrupt(self):
        """Interrupt current TTS output — stop audio playback.

        Called when the user speaks (VAD fires) mid-response.
        This is synchronous and safe to call from threads.
        """
        logger.debug("VoicePipeline: Interrupt requested")
        # Use sync transition since we may be in a thread
        try:
            self.sm.transition_sync(VoiceState.INTERRUPTED)
        except VoiceStateError:
            pass  # Not in SPEAKING state — that's fine

        # Fire the on_speech_start callback if set (bridges to ChatSession.cancel_assistant)
        if self.on_speech_start:
            try:
                self.on_speech_start()
            except Exception as e:
                logger.error(f"VoicePipeline: interrupt callback error: {e}")

    def stop_listening(self):
        """Stop the listen loop and clean up resources.

        Synchronous — safe to call from anywhere.
        """
        self._stop_event.set()
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
        self._stt_executor.shutdown(wait=False)
        self.sm.reset_sync()
