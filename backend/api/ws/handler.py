"""
WebSocket chat handler — per-connection ChatSession class.
"""
import asyncio
import json
import re
import logging

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from backend.api.deps import settings, memory, tts, agent, relationship, wakeword, mcp, orchestrator, llm, companion
from backend.api.ws.tts_service import OrderedTTSScheduler, synthesize_sentence, synthesize_now
from backend.core.translation import TranslationService
from backend.core.orchestrator import AgentProtocol
from pathlib import Path
from backend.core.paths import CHARACTERS_DIR, PROJECT_ROOT
from backend.voice.pipeline import VoicePipeline
from backend.core.errors import ServiceError

logger = logging.getLogger(__name__)


def _normalize_error(error_text: str) -> str:
    """Normalize common error messages to user-friendly versions."""
    import re as _re

    m = _re.search(r'\{.*\}', error_text, _re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group())
            inner = obj.get('error', obj)
            if isinstance(inner, dict):
                msg = inner.get('message', '')
                if msg:
                    error_text = msg
        except Exception:
            pass

    friendly = {
        "rate limit": "Rate limit exceeded. Please wait and try again.",
        "quota exceeded": "Quota exceeded. Check your plan and billing.",
        "RESOURCE_EXHAUSTED": "Quota exceeded. Check your plan and billing.",
        "API key not set": "API key not configured. Go to Settings > Providers to set it.",
        "content must be a string": "This provider doesn't support image input. Try a different model or remove the image.",
        "unsupported image format": "The image format is not supported. Try a different image.",
        "image_url is not supported": "This provider doesn't support image input. Try a different model or remove the image.",
        "401": "Authentication failed. Check your API key.",
        "402": "Payment required. Check your account billing.",
    }
    # Collapse all whitespace so "rate\nlimit\nexceeded" matches "rate limit"
    normalized = _re.sub(r'\s+', ' ', error_text.lower()).strip()

    for key, msg in friendly.items():
        if key.lower() in normalized:
            return msg
    return error_text


def _animation_dir(char_id: str) -> str:
    """Return the filesystem path to a character's animation directory."""
    data_dir = CHARACTERS_DIR / char_id / "anim"
    if data_dir.exists():
        return str(data_dir)
    repo_dir = PROJECT_ROOT / "backend" / "characters" / char_id / "anim"
    if repo_dir.exists():
        return str(repo_dir)
    return str(data_dir)


def _resolve_animation(text: str, char_id: str) -> str | None:
    """Resolve an animation URL from roleplay/action text by keyword matching."""
    import os
    words = text.lower().split()
    char_dir = _animation_dir(char_id)
    default_dir = _animation_dir("default")
    candidates = []
    if os.path.exists(default_dir):
        candidates.extend(os.listdir(default_dir))
    if char_id and char_id != "default" and os.path.exists(char_dir):
        candidates.extend(os.listdir(char_dir))
    for word in words:
        for f in candidates:
            if f.endswith(".vrma"):
                name = f.replace(".vrma", "").lower()
                if word == name or name.startswith(word) or word in name:
                    is_char = char_id and char_id != "default" and os.path.exists(os.path.join(char_dir, f))
                    base = char_id if is_char else "default"
                    return f"/characters/{base}/anim/{f}"
    return None


class _OrchestratorAgentAdapter:
    """Adapts the application's Agent to the AgentProtocol expected by the orchestrator.

    The orchestrator's ``dispatch_step`` calls ``handle_user_input(task_description)``
    on sub-agents.  This wrapper maps that call to the application agent's richer
    ``handle_user_input(text, images, relationship_context)`` interface.
    """

    def __init__(self, agent_type: str = "basic"):
        self.agent_type = agent_type

    async def handle_user_input(self, inp: str) -> AsyncGenerator[str, None]:
        """Delegate to the DI-provided application agent."""
        app_agent = agent()
        async for chunk in app_agent.handle_user_input(inp):
            if isinstance(chunk, str):
                yield chunk
            elif isinstance(chunk, tuple):
                # Skip signals (emotion, thinking, etc.) — just yield text
                if chunk[0] in ("__text__",):
                    yield chunk[1]


class ChatSession:
    """Per-WebSocket connection state and message handling."""

    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.stream_idx: int = 0
        self.current_task: asyncio.Task | None = None
        self.voice_output_enabled: bool = False
        self.voice_pipeline = None
        self.voice_task = None
        self.wake_word_enabled: bool = False
        self.pending_tasks: list[asyncio.Task] = []
        self.client_caps: dict = {}
        self.client_platform: str = "web"
        self._main_loop = asyncio.get_running_loop()
        # Wire MCP client for /stats, /approve, /permission slash commands
        self._mcp_client = mcp()

    def _track_task(self, t: asyncio.Task):
        """Track a task and register safe cleanup on completion."""
        self.pending_tasks.append(t)
        t.add_done_callback(self._on_task_done)

    def _on_task_done(self, t: asyncio.Task):
        """Safely remove completed tasks, handling race conditions."""
        try:
            self.pending_tasks.remove(t)
        except ValueError:
            pass  # Already removed or never added

    async def send(self, payload: dict):
        try:
            await self.ws.send_json(payload)
        except Exception as e:
            logger.warning("WS send failed: %s", e)

    def _get_translation_service(self):
        """Lazy-init and return a TranslationService (or None if not configured)."""
        if not hasattr(self, "_translation_service"):
            self._translation_service = None
            try:
                base_url = settings().get("translation.base_url", "http://localhost:1188/translate")
                if base_url:
                    from backend.core.translation import TranslationService as _TS
                    self._translation_service = _TS(base_url=base_url)
            except Exception as e:
                logger.warning("Failed to init TranslationService: %s", e)
        return self._translation_service

    async def cancel_assistant(self):
        if self.current_task and not self.current_task.done():
            # Cancel all pending TTS tasks for this stream
            for t in list(self.pending_tasks):
                if not t.done():
                    t.cancel()
            # Compact completed tasks
            self.pending_tasks = [t for t in self.pending_tasks if not t.done()]
            self.current_task.cancel()
            self.current_task = None
            self.stream_idx += 1
            await self.send({"type": "tts_interrupt"})

    async def process_response(self, text: str, images: list = None):
        await self.cancel_assistant()
        self.stream_idx += 1
        this_stream = self.stream_idx
        t = asyncio.create_task(self._run_agent_loop(text, images, this_stream))
        self.current_task = t
        self._track_task(t)

    async def _run_agent_loop(self, text: str, images: list, this_stream: int):
        await self.send({"type": "chat_start", "role": "assistant"})
        await self.send({"type": "emotion", "emotion": "neutral"})
        await self.send({"type": "expression", "expression": "neutral"})

        tts_scheduler = OrderedTTSScheduler(translation_service=self._get_translation_service())
        try:
            full_response = ""
            sentence_buffer = ""
            sentence_idx = 0
            current_emotion = "neutral"

            char_id = settings().get("character.active", "default")
            rel_context = await relationship().get_context_string(char_id)

            it = agent().handle_user_input(text, images=images, relationship_context=rel_context)
            if asyncio.iscoroutine(it):
                logger.error(f"CRITICAL: agent().handle_user_input returned a coroutine instead of an async generator! it={it}")
                # Try to await it if it's a coroutine (this shouldn't happen with async def + yield)
                it = await it

            async for item in it:
                if this_stream != self.stream_idx:
                    break

                # Handle tuple signals
                if isinstance(item, tuple):
                    sig_type = item[0]
                    sig_val = item[1]

                    if sig_type == '__emotion__':
                        current_emotion = sig_val
                        await self.send({"type": "emotion", "emotion": current_emotion})
                    elif sig_type == '__expression__':
                        await self.send({"type": "expression", "expression": sig_val})
                    elif sig_type == '__thinking__':
                        await self.send({"type": "thinking", "text": sig_val})
                    elif sig_type == '__animation__':
                        anim_url = f"/characters/{char_id}/anim/{sig_val}.vrma"
                        anim_path = Path(_animation_dir(char_id)) / f"{sig_val}.vrma"
                        if not anim_path.is_file():
                            anim_url = None
                        await self.send({"type": "animation", "name": sig_val,
                                        "url": anim_url})
                    elif sig_type == '__avatar__':
                        await self._handle_avatar_signal(sig_val, current_emotion, full_response, sentence_buffer, char_id)
                        if sig_type == '__avatar__':
                            continue
                    elif sig_type == '__tool__':
                        await self.send({"type": "tool_call", "text": sig_val})
                    elif sig_type == '__error__':
                        await self.send({"type": "chat_append", "role": "assistant",
                                        "text": _normalize_error(str(sig_val)), "finished": True, "error": True})
                        return
                    elif sig_type == '__permission__':
                        await self.send({"type": "permission_request", "command": sig_val})
                    elif sig_type == '__roleplay__':
                        rp_text = f"*{sig_val}* "
                        full_response += rp_text
                        sentence_buffer += rp_text
                        anim_url = _resolve_animation(sig_val, char_id)
                        await self.send({"type": "roleplay", "text": sig_val, "animation_url": anim_url})
                    continue

                # Regular text token
                token = item
                full_response += token
                sentence_buffer += token
                await self.send({"type": "chat_append", "role": "assistant", "text": token, "finished": False})

                # Sentence-level TTS
                if self.voice_output_enabled and re.search(r'[.!?。！？]\s|[.!?。！？]$|,\s{10,}', sentence_buffer):
                    parts = re.split(r'(?<=[.!?。！？])\s', sentence_buffer)
                    if len(parts) > 1:
                        complete = parts[0].strip()
                        sentence_buffer = ' '.join(parts[1:])
                        if complete:
                            await self.send({"type": "voice_state", "state": "speaking"})
                            await tts_scheduler.submit(
                                sentence_idx, complete, current_emotion,
                                self.ws, this_stream, lambda: self.stream_idx)
                            sentence_idx += 1

            # Post-stream: relationship tracking
            if full_response.strip() and this_stream == self.stream_idx:
                try:
                    await relationship().analyze_message("user", text, char_id)
                    await relationship().analyze_message("assistant", full_response, char_id)
                except Exception as e:
                    logger.warning(f"Relationship tracking error: {e}")

            # Final TTS + cleanup
            if this_stream == self.stream_idx:
                await self.send({"type": "viseme", "value": 0.0})
                if self.voice_output_enabled and sentence_buffer.strip():
                    await self.send({"type": "voice_state", "state": "speaking"})
                    await tts_scheduler.submit(
                        sentence_idx, sentence_buffer.strip(), current_emotion,
                        self.ws, this_stream, lambda: self.stream_idx)

                await self.send({"type": "emotion", "emotion": "neutral"})
                await self.send({"type": "expression", "expression": "neutral"})

                # Optional full-response translation for display
                chat_msg = {"type": "chat_append", "role": "assistant", "text": "", "finished": True}
                if full_response.strip() and this_stream == self.stream_idx:
                    trans_svc = self._get_translation_service()
                    trans_enabled = settings().get("translation.enabled", False)
                    if trans_svc and trans_enabled:
                        try:
                            source = settings().get("translation.source_lang", "auto")
                            target = settings().get("translation.target_lang", "en")
                            translated = await trans_svc.translate(
                                full_response, source_lang=source, target_lang=target
                            )
                            if translated and translated != full_response:
                                chat_msg["text"] = translated
                                chat_msg["original_text"] = full_response
                        except Exception as exc:
                            logger.warning("Full response translation failed: %s", exc)
                if not chat_msg.get("text"):
                    chat_msg["text"] = full_response
                await self.send(chat_msg)

                if not tts_scheduler.is_empty:
                    await tts_scheduler.flush(self.ws, this_stream, lambda: self.stream_idx)
                    if this_stream == self.stream_idx:
                        await self.send({"type": "voice_state", "state": "idle"})

        except asyncio.CancelledError:
            await tts_scheduler.cancel()
            try:
                await self.send({"type": "voice_state", "state": "idle"})
            except Exception:
                pass
            raise
        except ServiceError as e:
            logger.error(f"Service error in agent loop: {e}")
            try:
                await self.send({"type": "chat_append", "role": "assistant",
                                "text": f"Error: {_normalize_error(str(e))}", "finished": True, "error": True})
                await self.send(e.to_dict())
                await self.send({"type": "voice_state", "state": "idle"})
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Agent error in loop: {e}")
            try:
                await self.send({"type": "chat_append", "role": "assistant",
                                "text": f"Error: {_normalize_error(str(e))}", "finished": True, "error": True})
                await self.send({"type": "error", "service": "agent",
                                 "message": str(e), "recoverable": False, "suggestion": "", "details": {}})
                await self.send({"type": "voice_state", "state": "idle"})
            except Exception:
                pass
        finally:
            # Compact completed tasks to prevent unbounded growth
            done_tasks = [t for t in self.pending_tasks if t.done()]
            for t in done_tasks:
                try:
                    self.pending_tasks.remove(t)
                except ValueError:
                    pass

    async def _handle_avatar_signal(self, sig_val, current_emotion, full_response, sentence_buffer, char_id):
        """Handle __avatar__ signals for emotion/expression/roleplay."""
        try:
            av = json.loads(sig_val)
            av_type = av.get("type") if isinstance(av, dict) else None
            if av_type == "emotion":
                await self.send({"type": "emotion", "emotion": av.get("emotion", "neutral")})
            elif av_type == "expression":
                await self.send({"type": "expression", "expression": av.get("expression", "neutral")})
            elif av_type == "visibility":
                await self.send({"type": "visibility", "visible": av.get("visible", True)})
            elif av_type == "roleplay":
                action = av.get("action", "")
                anim_url = _resolve_animation(action, char_id)
                await self.send({"type": "roleplay", "text": action, "animation_url": anim_url})
        except Exception:
            pass

    async def handle_command(self, cmd: str, data: dict):
        """Handle voice/avatar/speak commands."""
        if cmd in ("voice_output_on", "voice_on"):
            self.voice_output_enabled = True
            await self.send({"type": "voice_state", "state": "idle"})
        elif cmd in ("voice_output_off", "voice_off"):
            self.voice_output_enabled = False
            await self.send({"type": "voice_state", "state": "idle"})
        elif cmd == "voice_input_on":
            await self._voice_input_on()
        elif cmd == "voice_input_off":
            await self._voice_input_off()
        elif cmd == "wake_word_on":
            await self._wake_word_on()
        elif cmd == "wake_word_off":
            await self._wake_word_off()
        elif cmd == "avatar_set_visibility":
            await self.send({"type": "visibility", "visible": data.get("visible", True)})
        elif cmd == "speak":
            speak_text = data.get("text", "").strip()
            if speak_text:
                # Send voice_state to inform frontend that speaking is starting
                await self.send({"type": "voice_state", "state": "speaking"})
                t = asyncio.create_task(synthesize_now(speak_text, self.ws))
                self._track_task(t)
        elif cmd == "typing":
            # Frontend typing indicator — acknowledge to prevent silent fall-through
            pass
        elif cmd == "stop_typing":
            # Frontend stop-typing indicator — acknowledge to prevent silent fall-through
            pass
        elif cmd == "mcp_config_update":
            await self._handle_mcp_config_update(data)

    async def _handle_mcp_config_update(self, data: dict):
        """Handle MCP server configuration update from the frontend."""
        try:
            args_raw = data.get("args", "[]")
            if isinstance(args_raw, str):
                updates = json.loads(args_raw)
            else:
                updates = args_raw

            mcp_client = mcp()
            if not mcp_client:
                await self.send({"type": "mcp_config_updated", "error": "MCP client not available"})
                return

            s = settings()
            current_servers = s.get_mcp_servers()
            current_by_name = {sv["name"]: sv for sv in current_servers}

            for update in updates:
                name = update.get("name")
                enabled = update.get("enabled", False)
                if not name:
                    continue

                if name in current_by_name:
                    current_by_name[name]["enabled"] = enabled

                    # Disconnect if now disabled
                    if not enabled and name in mcp_client.sessions:
                        await mcp_client._close_server(name)
                        await self.send({"type": "mcp_server_disconnected", "server": name})
                        logger.info(f"MCP server '{name}' disconnected via config update")
                    # Connect if now enabled and not already connected
                    elif enabled and name not in mcp_client.sessions:
                        config = current_by_name[name]
                        await mcp_client._connect_from_config(name, config)
                        await self.send({"type": "mcp_server_connected", "server": name})
                        logger.info(f"MCP server '{name}' connected via config update")

            # Persist updated settings
            s.set("mcp.servers", current_servers)
            await self.send({"type": "mcp_config_updated"})
        except json.JSONDecodeError as e:
            logger.error(f"MCP config update: JSON parse error: {e}")
            await self.send({"type": "mcp_config_updated", "error": f"Invalid JSON: {e}"})
        except Exception as e:
            logger.error(f"MCP config update failed: {e}")
            await self.send({"type": "mcp_config_updated", "error": str(e)})

    async def _voice_input_on(self):
        stt_engine = settings().get("voice.stt_engine", "faster-whisper")
        if stt_engine == "browser":
            await self.send({"type": "voice_state", "state": "recording"})
            return

        if self.voice_pipeline is None:
            _main_loop = asyncio.get_running_loop()

            def on_transcription(text):
                logger.info(f"Voice transcription received: {text[:80]}...")
                try:
                    asyncio.run_coroutine_threadsafe(self.process_response(text), _main_loop)
                except Exception as e:
                    logger.error(f"Voice transcription dispatch failed: {e}")
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.send({"type": "user_message_from_voice", "text": text}), _main_loop)
                except Exception as e:
                    logger.error(f"Voice transcription send failed: {e}")

            def on_speech_start():
                try:
                    asyncio.run_coroutine_threadsafe(self.cancel_assistant(), _main_loop)
                except Exception as e:
                    logger.error(f"Voice speech start callback failed: {e}")

            from backend.voice.stt_configurator import configure_stt_pipeline
            voice_cfg = settings()
            self.voice_pipeline = VoicePipeline(
                agent_callback=on_transcription,
                on_speech_start=on_speech_start,
                stt_engine=stt_engine,
                settings=voice_cfg,
            )
            configure_stt_pipeline(self.voice_pipeline, stt_engine, voice_cfg)

        if self.voice_task is None or self.voice_task.done():
            if self.voice_task and self.voice_task.exception():
                logger.error(f"Previous voice task failed: {self.voice_task.exception()}")
            loop = asyncio.get_running_loop()
            self.voice_task = loop.run_in_executor(None, self.voice_pipeline.listen_loop)
        await self.send({"type": "voice_state", "state": "recording"})

    async def _voice_input_off(self):
        stt_engine = settings().get("voice.stt_engine", "faster-whisper")
        if stt_engine == "browser":
            await self.send({"type": "voice_state", "state": "idle"})
        else:
            if self.voice_pipeline:
                self.voice_pipeline.stop_listening()
            if self.voice_task and not self.voice_task.done():
                self.voice_task.cancel()
                self.voice_task = None
            self.voice_pipeline = None
            await self.send({"type": "voice_state", "state": "idle"})

    async def _wake_word_on(self):
        ww = wakeword()

        def _wakeword_callback():
            logger.info("Wake word detected!")
            self._main_loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self.process_response("Hey, I'm listening!")))

        ww.set_callback(_wakeword_callback)
        ok = ww.start()
        if ok:
            self.wake_word_enabled = True
            await self.send({"type": "wake_word_state", "enabled": True})
        else:
            await self.send({"type": "wake_word_state", "enabled": False,
                            "error": "Failed to start wake word detection. Is openwakeword installed?"})

    async def _wake_word_off(self):
        wakeword().stop()
        self.wake_word_enabled = False
        await self.send({"type": "wake_word_state", "enabled": False})

    async def handle_slash_command(self, cmd: str, args: str):
        """Handle slash commands (/clear, /new, /help, /settings, etc.)."""
        if cmd == "clear":
            await memory().clear()
            sid = memory().start_session()
            relationship()._cache.clear()
            await self.send({"type": "chat_append", "role": "system",
                            "text": "Memory cleared.", "finished": True, "session_id": sid})
        elif cmd == "new":
            sid = memory().start_session()
            await self.send({"type": "chat_append", "role": "system",
                            "text": f"New session started: {sid}", "finished": True, "session_id": sid})
        elif cmd == "help":
            help_text = (
                "Slash commands:\n"
                "/clear — clear history\n"
                "/new — start new session\n"
                "/rename <title> — rename current session\n"
                "/resume — show last 5 turns\n"
                "/provider <name> — switch provider\n"
                "/model <name> — switch model\n"
                "/status — show provider, model, session\n"
                "/compact — force memory compaction\n"
                "/memory — show memory stats\n"
                "/stats — show tool usage statistics\n"
                "/health — run live service health checks\n"
                "/settings — show settings (use /settings <key> <val> to set)\n"
                "/theme <dark|midnight|light|nord> — switch theme\n"
                "/character <name> — load a character\n"
                "/think — toggle thinking display\n"
                "/companion — toggle companion mode\n"
                "/permission <level> — set permission (readonly|confirm|full)\n"
                "/profile <name> — switch settings profile\n"
                "/help — show this"
            )
            await self.send({"type": "chat_append", "role": "system", "text": help_text, "finished": True})
        elif cmd == "provider":
            if args:
                # Parse subcommand pattern: /provider [add|set|rm] <name>
                # or legacy: /provider <name>
                arg_parts = args.split(maxsplit=1)
                sub = arg_parts[0].lower()
                if sub in ("add", "set", "rm") and len(arg_parts) > 1:
                    provider_name = arg_parts[1]
                else:
                    provider_name = sub
                loop = asyncio.get_running_loop()
                s_obj = settings()
                await loop.run_in_executor(None, lambda: s_obj.set("provider.active", provider_name))
                llm().reload_settings()
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Switched to provider: {provider_name}", "finished": True})
            else:
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Current provider: {settings().get('provider.active', 'gemini')}", "finished": True})
        elif cmd == "model":
            if args:
                provider = settings().get("provider.active", "gemini")
                loop = asyncio.get_running_loop()
                s = settings()
                await loop.run_in_executor(None, lambda: s.set(f"provider.{provider}.model", args))
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Switched model to: {args}", "finished": True})
            else:
                provider = settings().get("provider.active", "gemini")
                model = settings().get(f"provider.{provider}.model", "not set")
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Current model ({provider}): {model}", "finished": True})
        elif cmd == "compact":
            await self.send({"type": "chat_append", "role": "system", "text": "Compacting memory...", "finished": True})
            try:
                await memory().check_and_summarize()
                await self.send({"type": "chat_append", "role": "system", "text": "Memory compacted.", "finished": True})
            except Exception as e:
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Compaction failed: {e}", "finished": True})
        elif cmd == "status":
            s = settings()
            active = s.get("provider.active", "?")
            model = s.get(f"provider.{active}.model", "?")
            sid = memory().get_current_session()
            await self.send({"type": "chat_append", "role": "system",
                            "text": f"Provider: {active}\nModel: {model}\nSession: {sid}", "finished": True})
        elif cmd == "settings":
            if args:
                parts = args.strip().split(" ", 1)
                key = parts[0]
                val = parts[1] if len(parts) > 1 else None
                # Allowlist of settings keys that can be modified via slash command
                _SETTINGS_ALLOWLIST = {
                    "ui.theme", "ui.language", "ui.font_size", "ui.accent_color",
                    "ui.thinking_enabled", "ui.voice_input", "ui.voice_output",
                    "character.active", "character.greeting",
                    "provider.active", "profile",
                    "companion.enabled",
                    "translation.enabled", "translation.source_lang", "translation.target_lang",
                    "memory.enabled", "memory.context_window", "memory.fact_extraction",
                    "privacy.metrics_opt_out", "privacy.local_only_mode",
                }
                if val:
                    if key not in _SETTINGS_ALLOWLIST:
                        await self.send({"type": "chat_append", "role": "system",
                                        "text": f"Cannot set '{key}' via slash command. Use the Settings UI for provider/credential keys.",
                                        "finished": True})
                    else:
                        loop = asyncio.get_running_loop()
                        s_obj = settings()
                        await loop.run_in_executor(None, lambda: s_obj.set(key, val))
                        await self.send({"type": "chat_append", "role": "system",
                                        "text": f"Setting {key} = {val}", "finished": True})
                else:
                    val = settings().get(key, "not set")
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"{key} = {val}", "finished": True})
            else:
                s_obj = settings()
                keys = ["provider.active", "ui.theme", "voice.tts_provider", "ui.language"]
                lines = []
                for k in keys:
                    lines.append(f"{k} = {s_obj.get(k, 'not set')}")
                await self.send({"type": "chat_append", "role": "system",
                                "text": "\n".join(lines), "finished": True})
        elif cmd == "memory":
            sessions = memory().get_sessions()
            current_sid = memory().get_current_session()
            total_msgs = sum(s.get("message_count", 0) for s in sessions)
            text = (
                f"Memory stats:\n"
                f"Sessions: {len(sessions)}\n"
                f"Total messages: {total_msgs}\n"
                f"Current session: {current_sid}"
            )
            await self.send({"type": "chat_append", "role": "system", "text": text, "finished": True})
        elif cmd == "stats":
            mcp_client = getattr(self, '_mcp_client', None)
            if mcp_client and hasattr(mcp_client, 'analytics'):
                stats = mcp_client.analytics.get_stats()
                lines = [f"Tool stats ({stats['total_calls']} calls, {stats['total_failures']} failures):"]
                for tname, tinfo in stats.get("tools", {}).items():
                    rate = tinfo["success_rate"]
                    avg = tinfo["avg_latency_ms"]
                    lines.append(f"  {tname}: {tinfo['calls']} calls, {rate}% success, {avg}ms avg")
                text = "\n".join(lines)
            else:
                text = "Tool analytics not available"
            await self.send({"type": "chat_append", "role": "system", "text": text, "finished": True})
        elif cmd == "theme":
            valid_themes = {"dark", "midnight", "light", "nord"}
            if args and args.strip().lower() in valid_themes:
                theme = args.strip().lower()
                loop = asyncio.get_running_loop()
                s_obj = settings()
                await loop.run_in_executor(None, lambda: s_obj.set("ui.theme", theme))
                await self.send({"type": "theme_change", "theme": theme})
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Theme switched to: {theme}", "finished": True})
            else:
                current = settings().get("ui.theme", "dark")
                valid = ", ".join(sorted(valid_themes))
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Current theme: {current}\nValid themes: {valid}", "finished": True})
        elif cmd == "rename":
            if args:
                try:
                    old = memory().get_current_session()
                    new = await memory().rename_session(old, args.strip())
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Session renamed → \"{new}\"", "finished": True})
                except ValueError as e:
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Error: {e}", "finished": True})
                except Exception as e:
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Rename failed: {e}", "finished": True})
            else:
                await self.send({"type": "chat_append", "role": "system",
                                "text": "Usage: /rename <new title>", "finished": True})

        elif cmd == "think":
            await self.send({"type": "chat_append", "role": "system",
                            "text": "Thinking display toggled.", "finished": True})
        elif cmd == "companion":
            try:
                companion_enabled = settings().get("companion.enabled", False)
                settings().set("companion.enabled", not companion_enabled)
                state = "ON" if not companion_enabled else "OFF"
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Companion mode {state}", "finished": True})
            except Exception as e:
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Companion toggle failed: {e}", "finished": True})
        elif cmd == "resume":
            try:
                sid = memory().get_current_session()
                turns = memory().get_session_turns(sid, turns=5)
                if turns:
                    lines = [f"Last {len(turns)} turns of {sid}:"]
                    for turn in turns:
                        role = turn.get("role", "?").upper()
                        content = turn.get("content", "")[:200]
                        lines.append(f"{role}: {content}")
                    text = "\n".join(lines)
                else:
                    text = f"No turns found for session {sid}"
                await self.send({"type": "chat_append", "role": "system", "text": text, "finished": True})
            except Exception as e:
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Resume failed: {e}", "finished": True})
        elif cmd == "health":
            try:
                from backend.core.health import get_registry
                registry = get_registry()
                results = await registry.check_all()
                if results:
                    lines = ["Service Health:"]
                    for name, s in sorted(results.items()):
                        st = s.get("status", "?")
                        icon = {"ok": "\u2713", "degraded": "\u26a0", "down": "\u2717"}.get(st, "\u00b7")
                        lat = s.get("latency_ms", 0)
                        lat_str = f" ({lat:.0f}ms)" if lat else ""
                        lines.append(f"  {icon} {name}: {st}{lat_str}")
                    text = "\n".join(lines)
                else:
                    text = "No health data available"
                await self.send({"type": "chat_append", "role": "system", "text": text, "finished": True})
            except Exception as e:
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Health check failed: {e}", "finished": True})
        elif cmd == "character":
            if args:
                name = args.strip()
                # Sanitize character name: prevent path traversal
                if '..' in name or '/' in name or '\\' in name or not name.isprintable():
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Invalid character name: '{name}'", "finished": True})
                else:
                    from backend.core.paths import CHARACTERS_DIR
                    char_dir = str(CHARACTERS_DIR / name)
                    import os as _os
                    if _os.path.isdir(char_dir):
                        settings().set("character.active", name)
                        await self.send({"type": "chat_append", "role": "system",
                                        "text": f"Loaded character: {name}", "finished": True})
                    else:
                        chars = [d for d in _os.listdir(str(CHARACTERS_DIR))
                                 if _os.path.isdir(_os.path.join(str(CHARACTERS_DIR), d))]
                        await self.send({"type": "chat_append", "role": "system",
                                        "text": f"Character '{name}' not found. Available: {', '.join(chars)}",
                                        "finished": True})
            else:
                current = settings().get("character.active", "none")
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Current character: {current}", "finished": True})
        elif cmd == "permission":
            valid_levels = {"readonly", "confirm", "full"}
            if args and args.strip().lower() in valid_levels:
                level = args.strip().lower()
                mcp_client = getattr(self, '_mcp_client', None)
                if mcp_client and hasattr(mcp_client, 'set_permission_level'):
                    mcp_client.set_permission_level(level)
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Permission level set to: {level}", "finished": True})
                else:
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Permission level changed to {level} (local only)", "finished": True})
            else:
                current = getattr(getattr(self, '_mcp_client', None), 'permissions', None)
                level = current.level.value if current else "full"
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Current permission level: {level}\nValid: readonly, confirm, full",
                                "finished": True})
        elif cmd == "profile":
            if args:
                from backend.core.config.settings import switch_profile
                try:
                    switch_profile(args.strip())
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Profile switched to: {args.strip()}", "finished": True})
                except ValueError as e:
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Error: {e}", "finished": True})
            else:
                from backend.core.config.settings import get_effective_settings
                s = get_effective_settings()
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Current profile: {s.get('profile', 'default')}", "finished": True})
        elif cmd == "plan":
            await self._handle_plan_command(args)
        elif cmd == "plans":
            """Alias for /plan list."""
            await self._handle_plan_command("list")
        else:
            await self.send({"type": "chat_append", "role": "system",
                            "text": f"Unknown command: /{cmd}. Try /help", "finished": True})

    async def _handle_plan_command(self, args: str):
        """Handle /plan <subcommand> [args].

        Subcommands:
          create <name> <json_steps>   — create a new plan
          list                          — list all plans
          status <plan_id>              — show plan status
          run <plan_id>                 — execute a plan
          cancel <plan_id>              — cancel a pending/running plan
        """
        parts = args.strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"

        try:
            if sub == "create":
                if len(parts) < 2:
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": "Usage: /plan create <name> <json_steps>", "finished": True})
                    return
                # Parse: name + JSON steps array
                create_args = parts[1]
                # Try to extract name (everything before first '{')
                brace_idx = create_args.find("{")
                if brace_idx < 0:
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": "Missing JSON steps array. Usage: /plan create <name> <json_steps>",
                                    "finished": True})
                    return
                name = create_args[:brace_idx].strip() or "Unnamed Plan"
                steps_json = create_args[brace_idx:]
                steps = json.loads(steps_json)
                if not isinstance(steps, list):
                    raise ValueError("steps must be a JSON array")

                orch = orchestrator()
                plan = orch.create_plan(name, steps)
                # Persist plan
                orch.save_state()
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Plan created: {plan.name} ({plan.id})\n"
                                        f"Steps: {len(plan.steps)}\n"
                                        f"Run with: /plan run {plan.id}",
                                "finished": True})

            elif sub == "list":
                orch = orchestrator()
                plans = list(orch.plans.values())
                if not plans:
                    text = "No plans."
                else:
                    lines = ["**Plans:**"]
                    for p in plans:
                        done = sum(1 for s in p.steps if s.status == "done")
                        lines.append(f"  {p.id}: {p.name} — {p.status} ({done}/{len(p.steps)} steps)")
                    text = "\n".join(lines)
                await self.send({"type": "chat_append", "role": "system", "text": text, "finished": True})

            elif sub == "status":
                if len(parts) < 2:
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": "Usage: /plan status <plan_id>", "finished": True})
                    return
                plan_id = parts[1].strip()
                orch = orchestrator()
                plan = orch.get_plan(plan_id)
                if not plan:
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Plan {plan_id!r} not found.", "finished": True})
                    return
                lines = [f"**Plan:** {plan.name} ({plan.id})", f"Status: {plan.status}"]
                for s in plan.steps:
                    icon = {"done": "✅", "running": "🔄", "failed": "❌", "pending": "⏳", "blocked": "🔒"}
                    lines.append(f"  {icon.get(s.status, '❓')} {s.id}: {s.description} [{s.status}]")
                if plan.steps:
                    lines.append(f"  Runnable: {[s.id for s in orch.get_runnable_steps(plan_id)]}")
                await self.send({"type": "chat_append", "role": "system",
                                "text": "\n".join(lines), "finished": True})

            elif sub == "run":
                if len(parts) < 2:
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": "Usage: /plan run <plan_id>", "finished": True})
                    return
                plan_id = parts[1].strip()
                orch = orchestrator()
                if not orch.get_plan(plan_id):
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Plan {plan_id!r} not found.", "finished": True})
                    return

                # Set up WS sender for swarm updates
                orch.set_ws_sender(lambda msg: self.send(msg))

                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Executing plan {plan_id}...", "finished": True})

                def agent_factory(agent_type: str = "basic") -> AgentProtocol:
                    return _OrchestratorAgentAdapter(agent_type)

                result = await orch.execute_plan(plan_id, agent_factory)
                # Persist updated state
                orch.save_state()

                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Plan {result['status']}: {result}",
                                "finished": True})

            elif sub == "cancel":
                if len(parts) < 2:
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": "Usage: /plan cancel <plan_id>", "finished": True})
                    return
                plan_id = parts[1].strip()
                orch = orchestrator()
                orch.cancel_plan(plan_id)
                orch.save_state()
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Plan {plan_id} cancelled.", "finished": True})

            else:
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Unknown plan subcommand: {sub}. Try: create, list, status, run, cancel",
                                "finished": True})

        except json.JSONDecodeError as e:
            await self.send({"type": "chat_append", "role": "system",
                            "text": f"Invalid JSON: {e}", "finished": True})
        except Exception as e:
            logger.error("Plan command error: %s", e)
            await self.send({"type": "chat_append", "role": "system",
                            "text": f"Plan command failed: {e}", "finished": True})

    async def cleanup(self):
        """Cancel all pending tasks and stop voice/wake word."""
        logger.info("ChatSession cleanup: cancelling pending tasks...")
        # Cancel all pending tasks
        for t in self.pending_tasks:
            if not t.done():
                t.cancel()
        # Wait briefly for tasks to finish cancellation
        if self.pending_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.pending_tasks, return_exceptions=True),
                    timeout=5.0
                )
            except (asyncio.TimeoutError, Exception):
                logger.debug("Timeout waiting for pending tasks to cancel")

        # Stop voice pipeline cleanly
        if self.voice_pipeline:
            try:
                self.voice_pipeline.stop_listening()
            except Exception as e:
                logger.warning(f"Voice pipeline stop failed: {e}")
            self.voice_pipeline = None
        if self.voice_task and not self.voice_task.done():
            self.voice_task.cancel()
            try:
                await asyncio.wait_for(self.voice_task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
            self.voice_task = None

        # Stop wake word
        if self.wake_word_enabled:
            try:
                wakeword().stop()
            except Exception:
                pass
            self.wake_word_enabled = False

        # Send voice state idle so frontend can reset UI
        try:
            if self.ws.client_state.value == 1:  # CONNECTED
                await self.send({"type": "voice_state", "state": "idle"})
        except Exception:
            pass

        # Background: update user profile from this session
        try:
            sid = memory().get_current_session()
            msgs = memory().get_session_messages(sid)
            if len(msgs) >= 3:
                from backend.core.user_profile import UserProfile
                profile = UserProfile()
                asyncio.create_task(
                    profile.update_from_session(
                        messages=msgs,
                        llm_caller=lambda prompt: llm().generate(
                            [{"role": "user", "content": prompt}],
                        ),
                    )
                )
        except Exception as e:
            logger.debug("Failed to save conversation history on shutdown: %s", e)

    async def handle_client_hello(self, data: dict):
        """Handle client_hello — acknowledge capabilities from native shell."""
        caps = data.get("capabilities", {})
        platform = data.get("platform", "web")
        logger.info("Client hello: platform=%s capabilities=%s", platform, caps)
        # Store capabilities for use during this session
        self.client_caps = caps
        self.client_platform = platform
        await self.send({
            "type": "server_hello",
            "platform": platform,
            "capabilities": {
                "push_enabled": True,
                "tts_enabled": bool(settings().get("voice.tts_provider")),
                "version": 1,
            },
        })

    async def run(self):
        """Main message loop."""
        # Register with companion scheduler
        sched = companion()
        if sched:
            session_id = memory().get_current_session()
            sched.register_session(session_id, self.send)
            # Notify companion that user joined
            try:
                from backend.core.companion.events import CompanionEvent, CompanionEventType
                await sched.on_event(CompanionEvent(
                    event_type=CompanionEventType.USER_JOINED,
                    data={"session_id": session_id},
                ))
            except Exception as e:
                logger.debug("Companion USER_JOINED event failed: %s", e)
        try:
            while True:
                data = await self.ws.receive_json()
                msg_type = data.get("type")

                if msg_type == "client_hello":
                    await self.handle_client_hello(data)
                elif msg_type == "command":
                    await self.handle_command(data.get("command", ""), data)
                elif msg_type == "slash_command":
                    await self.handle_slash_command(data.get("command", "").lower(), data.get("args", ""))
                elif msg_type == "idle_prompt_request":
                    try:
                        text = await agent().generate_idle_prompt()
                        if text:
                            await self.send({"type": "idle_prompt", "text": text})
                        asyncio.create_task(agent().subconscious_reflect())
                    except Exception as e:
                        logger.warning(f"Idle prompt request failed: {e}")
                elif msg_type == "user_message":
                    text = data.get("text", "").strip()
                    images = data.get("images", None)
                    sid = data.get("session_id", "").strip()
                    if sid:
                        memory().set_current_session(sid)
                    if text or images:
                        await self.process_response(text, images)

                elif msg_type == "avatar_life_event":
                    event = data.get("event", "")
                    logger.info(f"Avatar life event: {event}")
                    if event == "bored":
                        try:
                            text = await agent().generate_idle_prompt()
                            if text:
                                await self.process_response(text)
                            asyncio.create_task(agent().subconscious_reflect())
                        except Exception as e:
                            logger.warning(f"Bored prompt failed: {e}")

                elif msg_type == "interrupt":
                    if data.get("action") == "stop_audio_and_animation":
                        await self.cancel_assistant()
                        await self.send({
                            "type": "interrupt",
                            "action": "stop_audio_and_animation",
                        })

                elif msg_type == "ping":
                    # Heartbeat ping — respond with pong immediately
                    await self.send({"type": "pong"})

                elif msg_type == "idle_enter":
                    # User went idle — notify companion scheduler
                    sched = companion()
                    if sched:
                        from backend.core.companion.events import CompanionEvent, CompanionEventType
                        await sched.on_event(CompanionEvent(
                            event_type=CompanionEventType.IDLE_ENTER,
                            data={"session_id": memory().get_current_session()},
                        ))

                elif msg_type == "idle_exit":
                    # User returned from idle — notify companion scheduler
                    sched = companion()
                    if sched:
                        from backend.core.companion.events import CompanionEvent, CompanionEventType
                        await sched.on_event(CompanionEvent(
                            event_type=CompanionEventType.IDLE_EXIT,
                            data={"session_id": memory().get_current_session()},
                        ))

                elif msg_type == "retry_tool":
                    # Retry a failed tool call from the frontend
                    tool_name = data.get("tool", "")
                    tool_args = data.get("args", {})
                    if tool_name:
                        try:
                            mcp_client = mcp()
                            if mcp_client:
                                result = await mcp_client.call_tool(tool_name, tool_args)
                            else:
                                result = "No MCP client available"
                            await self.send({
                                "type": "tool_result",
                                "tool_name": tool_name,
                                "result": result,
                                "error": None,
                            })
                        except Exception as e:
                            logger.warning(f"Tool retry '{tool_name}' failed: {e}")
                            await self.send({
                                "type": "tool_result",
                                "tool_name": tool_name,
                                "result": None,
                                "error": str(e),
                            })

        except WebSocketDisconnect:
            logger.warning("Chat WebSocket disconnected")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            # Unregister from companion scheduler
            sched = companion()
            if sched:
                try:
                    sched.unregister_session(memory().get_current_session())
                except Exception:
                    pass
            await self.cleanup()


async def handle_chat(websocket: WebSocket):
    await websocket.accept()
    session = ChatSession(websocket)
    await session.run()
