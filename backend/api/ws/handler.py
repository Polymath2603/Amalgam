"""
WebSocket chat handler — per-connection ChatSession class.
"""
import asyncio
import json
import re
import logging

from fastapi import WebSocket, WebSocketDisconnect
from backend.api.deps import settings, memory, tts, agent, relationship, wakeword
from backend.api.ws.tts_service import synthesize_sentence, synthesize_now
from pathlib import Path
from backend.core.paths import CHARACTERS_DIR, PROJECT_ROOT
from backend.voice.pipeline import VoicePipeline

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
    for key, msg in friendly.items():
        if key.lower() in error_text.lower():
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
        except Exception:
            pass

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

        tts_tasks = []
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
                        await self.send({"type": "animation", "name": sig_val,
                                        "url": f"/characters/{char_id}/anim/{sig_val}.vrma"})
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
                            t = asyncio.create_task(synthesize_sentence(
                                complete, sentence_idx, this_stream, self.stream_idx,
                                self.ws, current_emotion))
                            self._track_task(t)
                            tts_tasks.append(t)
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
                    t = asyncio.create_task(synthesize_sentence(
                        sentence_buffer.strip(), sentence_idx, this_stream,
                        self.stream_idx, self.ws, current_emotion))
                    self._track_task(t)
                    tts_tasks.append(t)

                await self.send({"type": "emotion", "emotion": "neutral"})
                await self.send({"type": "expression", "expression": "neutral"})
                await self.send({"type": "chat_append", "role": "assistant", "text": "", "finished": True})

                if tts_tasks:
                    await asyncio.gather(*tts_tasks, return_exceptions=True)
                    if this_stream == self.stream_idx:
                        await self.send({"type": "voice_state", "state": "idle"})

        except asyncio.CancelledError:
            for t in tts_tasks:
                if not t.done():
                    t.cancel()
            raise
        except Exception as e:
            logger.error(f"Agent error in loop: {e}")
            await self.send({"type": "chat_append", "role": "assistant",
                            "text": f"Error: {_normalize_error(str(e))}", "finished": True, "error": True})
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
                t = asyncio.create_task(synthesize_now(speak_text, self.ws))
                self._track_task(t)

    async def _voice_input_on(self):
        stt_engine = settings().get("voice.stt_engine", "faster-whisper")
        if stt_engine == "browser":
            await self.send({"type": "voice_state", "state": "recording"})
            return

        if self.voice_pipeline is None:
            _main_loop = asyncio.get_running_loop()

            def on_transcription(text):
                asyncio.run_coroutine_threadsafe(self.process_response(text), _main_loop)
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.send({"type": "user_message_from_voice", "text": text}), _main_loop)
                except Exception as e:
                    logger.error(f"Voice transcription send failed: {e}")

            def on_speech_start():
                asyncio.run_coroutine_threadsafe(self.cancel_assistant(), _main_loop)

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
            main_loop = asyncio.get_event_loop()
            main_loop.call_soon_threadsafe(
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
                "/provider <name> — switch provider\n"
                "/model <name> — switch model\n"
                "/session <id> — show/load session\n"
                "/status — show current provider, model, session\n"
                "/compact — force memory compaction\n"
                "/settings — show all settings (use /settings <key> <val> to set)\n"
                "/memory — show memory stats\n"
                "/stats — show tool usage statistics\n"
                "/theme <dark|midnight|light|nord> — switch theme\n"
                "/character <name> — load a character\n"
                "/approve <tool> — approve a dangerous tool for one use\n"
                "/permission <readonly|confirm|full> — set permission level\n"
                "/help — show this"
            )
            await self.send({"type": "chat_append", "role": "system", "text": help_text, "finished": True})
        elif cmd == "provider":
            if args:
                loop = asyncio.get_running_loop()
                s = settings()
                await loop.run_in_executor(None, lambda: s.set("provider.active", args))
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Switched to provider: {args}", "finished": True})
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
        elif cmd == "session":
            if args:
                sid = args.strip()
                memory().set_current_session(sid)
                msgs = memory().get_session_messages(sid)
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Loaded session: {sid} ({len(msgs)} messages)",
                                "finished": True, "session_id": sid})
            else:
                sid = memory().get_current_session()
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Current session: {sid}", "finished": True})
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
                if val:
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
            stats = await memory().get_stats()
            text = (
                f"Memory stats:\n"
                f"Sessions: {stats.get('sessions', '?')}\n"
                f"Messages: {stats.get('messages', '?')}\n"
                f"Current session: {memory().get_current_session()}"
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
        elif cmd == "character":
            if args:
                name = args.strip()
                char_dir = f"/home/leonardo/Workplace/k/characters/{name}"
                import os as _os
                if _os.path.isdir(char_dir):
                    settings().set("character.active", name)
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Loaded character: {name}", "finished": True})
                else:
                    chars = [d for d in _os.listdir("/home/leonardo/Workplace/k/characters/")
                             if _os.path.isdir(_os.path.join("/home/leonardo/Workplace/k/characters/", d))]
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Character '{name}' not found. Available: {', '.join(chars)}",
                                    "finished": True})
            else:
                current = settings().get("character.active", "none")
                await self.send({"type": "chat_append", "role": "system",
                                "text": f"Current character: {current}", "finished": True})
        elif cmd == "approve":
            if args:
                tool_name = args.strip()
                mcp_client = getattr(self, '_mcp_client', None)
                if mcp_client and hasattr(mcp_client, 'approve_tool'):
                    mcp_client.approve_tool(tool_name)
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": f"Approved tool: {tool_name}", "finished": True})
                else:
                    await self.send({"type": "chat_append", "role": "system",
                                    "text": "MCP client not available for approval", "finished": True})
            else:
                await self.send({"type": "chat_append", "role": "system",
                                "text": "Usage: /approve <tool_name>", "finished": True})
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
        else:
            await self.send({"type": "chat_append", "role": "system",
                            "text": f"Unknown command: /{cmd}. Try /help", "finished": True})

    async def cleanup(self):
        """Cancel all pending tasks and stop voice/wake word."""
        for t in self.pending_tasks:
            if not t.done():
                t.cancel()
        if self.voice_pipeline:
            self.voice_pipeline.stop_listening()
        if self.voice_task and not self.voice_task.done():
            self.voice_task.cancel()
        if self.wake_word_enabled:
            try:
                wakeword().stop()
            except Exception:
                pass

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
                    if text or images:
                        await self.process_response(text, images)

        except WebSocketDisconnect:
            logger.warning("Chat WebSocket disconnected")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            await self.cleanup()


async def handle_chat(websocket: WebSocket):
    await websocket.accept()
    session = ChatSession(websocket)
    await session.run()
