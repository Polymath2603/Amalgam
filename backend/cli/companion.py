"""
Companion mode — terminal-based interactive session with full command set.
Usage: python -m backend.cli.companion

Commands: /help, /quit, /clear, /new, /status, /rename, /export, /sessions,
          /session <id>, /provider <name>, /model <name>, /compact,
          /settings [key] [val], /memory, /stats, /theme <name>,
          /character <name>, /profile <name>, /think, /companion on|off
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────────────────────────

_VALID_THEMES = {"dark", "midnight", "light", "nord"}
_VALID_PROFILES = {"token-friendly", "default", "quality", "custom"}


def _print_banner():
    print()
    print("═" * 52)
    print("  Amalgam Companion Mode  —  type /help for commands")
    print("═" * 52)
    print()


def _format_settings_table(settings_obj, keys: list[str]) -> str:
    lines = []
    for k in keys:
        v = settings_obj.get(k, "not set")
        lines.append(f"  {k:<32} {v}")
    return "\n".join(lines)


def _yes_no(prompt: str) -> bool:
    """Ask a yes/no question."""
    while True:
        ans = input(f"{prompt} [y/n]: ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


# ── agent proxy — wires deps into the CLI REPL ──────────────────────────────

class _AgentProxy:
    """Lazily-resolved agent from the shared DI container."""

    def __init__(self):
        self._agent = None

    def _ensure(self):
        if self._agent is None:
            from backend.core.deps import agent
            self._agent = agent()
        return self._agent

    def handle_user_input(self, text: str, **kw) -> AsyncGenerator:
        return self._ensure().handle_user_input(text, **kw)

    def generate_idle_prompt(self) -> str:
        return self._ensure().generate_idle_prompt() if hasattr(self._ensure(), 'generate_idle_prompt') else ""


# ── REPL core ────────────────────────────────────────────────────────────────

class CompanionREPL:
    """Full interactive REPL with all slash commands."""

    def __init__(self):
        from backend.core.deps import get_shared
        self._shared = get_shared()

        self._settings = self._shared["settings"]
        self._memory = self._shared["memory"]
        self._agent = _AgentProxy()

        # Runtime toggles
        self._show_thinking = True
        self._companion_enabled = False  # proactive idle prompts
        self._idle_task: Optional[asyncio.Task] = None

    # ── helpers ──────────────────────────────────────────────────────────

    def _settings_singleton(self):
        return self._settings

    def _memory_singleton(self):
        return self._memory

    def _reload_settings(self):
        """Force-sync settings from disk."""
        self._settings.load()

    def _get_provider(self) -> str:
        return self._settings.get("provider.active", "gemini")

    def _get_model(self) -> str:
        p = self._get_provider()
        return self._settings.get(f"provider.{p}.model", "not set")

    def _get_session(self) -> str:
        return self._memory.get_current_session()

    def _print(self, text: str):
        """Print a system-formatted message."""
        print(f"  {text}")

    # ── command dispatch ─────────────────────────────────────────────────

    async def _cmd_help(self):
        self._print("Commands:")
        cmds = [
            ("/help", "Show this help"),
            ("/quit", "Exit companion mode"),
            ("/clear", "Clear session memory (start fresh)"),
            ("/new", "Start a new session"),
            ("/rename <title>", "Rename current session"),
            ("/export [file]", "Export conversation to file (default: ./export_<session>.md)"),
            ("/sessions", "List all sessions"),
            ("/session <id>", "Load a specific session"),
            ("/status", "Show provider, model, session, profile"),
            ("/provider <name>", "Switch provider (gemini, ollama, openrouter, …)"),
            ("/model <name>", "Switch model for current provider"),
            ("/compact", "Force memory compaction"),
            ("/settings [key] [val]", "Show/set a setting"),
            ("/memory", "Show memory usage stats"),
            ("/stats", "Show tool-usage analytics"),
            ("/theme <name>", "Switch UI theme (dark, midnight, light, nord)"),
            ("/character <name>", "Load a different character"),
            ("/profile <name>", "Switch settings profile"),
            ("/think", "Toggle thinking-display on/off"),
            ("/companion on|off", "Toggle idle proactive prompts"),
            ("/approve <tool>", "Approve a tool for one use"),
            ("/permission <level>", "Set permission level (readonly|confirm|full)"),
        ]
        for cmd, desc in cmds:
            print(f"  {cmd:<28} {desc}")

    async def _cmd_clear(self):
        await self._memory.clear()
        self._memory.start_session()
        self._print("Memory cleared. Started fresh session.")

    async def _cmd_new(self):
        sid = self._memory.start_session()
        self._print(f"New session started: {sid}")

    async def _cmd_rename(self, args: str):
        if not args:
            self._print("Usage: /rename <new title>")
            return
        try:
            old = self._memory.get_current_session()
            new = await self._memory.rename_session(old, args.strip())
            self._print(f"Session renamed → \"{new}\"")
        except ValueError as e:
            self._print(f"Error: {e}")
        except Exception as e:
            self._print(f"Rename failed: {e}")

    async def _cmd_export(self, args: str):
        session_id = self._memory.get_current_session()
        msgs = self._memory.get_session_messages(session_id)
        if not msgs:
            self._print("No messages in current session.")
            return
        out_path = args.strip() or f"export_{session_id[:20]}.md"
        if not out_path.endswith(".md"):
            out_path += ".md"
        try:
            lines = [f"# Amalgam Conversation — {session_id}\n"]
            for m in msgs:
                role = m["role"].upper()
                content = m["content"]
                lines.append(f"**{role}:** {content}\n")
            Path(out_path).write_text("\n".join(lines), encoding="utf-8")
            self._print(f"Exported {len(msgs)} messages → {out_path}")
        except OSError as e:
            self._print(f"Export failed: {e}")

    async def _cmd_sessions(self):
        sessions = self._memory.get_sessions()
        if not sessions:
            self._print("No sessions found.")
            return
        current = self._memory.get_current_session()
        self._print(f"Total: {len(sessions)} session(s)  (current marked ←)")
        for s in sessions[:30]:
            sid = s.get("id", "?")
            title = s.get("title", "untitled")[:50]
            msgs = s.get("message_count", 0)
            mark = " ←" if sid == current else ""
            print(f"  {sid:<32} {title:<30} {msgs:>4} msgs{mark}")

    async def _cmd_session(self, args: str):
        if not args:
            self._cmd_sessions()
            return
        sid = args.strip()
        if not self._memory.session_exists(sid):
            self._print(f"Session '{sid}' not found.")
            return
        self._memory.set_current_session(sid)
        msgs = self._memory.get_session_messages(sid)
        self._print(f"Loaded session: {sid} ({len(msgs)} messages)")

    async def _cmd_status(self):
        p = self._get_provider()
        m = self._get_model()
        sid = self._memory.get_current_session()
        profile = self._settings.get("profile", "default")
        companion = "ON" if self._companion_enabled else "OFF"
        self._print(
            f"Provider:     {p}\n"
            f"Model:        {m}\n"
            f"Session:      {sid}\n"
            f"Profile:      {profile}\n"
            f"Companion:    {companion}"
        )

    async def _cmd_provider(self, args: str):
        if not args:
            self._print(f"Current provider: {self._get_provider()}")
            return
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: self._settings.set("provider.active", args.strip())
        )
        self._reload_settings()
        self._print(f"Switched to provider: {args.strip()}")

    async def _cmd_model(self, args: str):
        if not args:
            self._print(f"Current model ({self._get_provider()}): {self._get_model()}")
            return
        p = self._get_provider()
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: self._settings.set(f"provider.{p}.model", args.strip())
        )
        self._reload_settings()
        self._print(f"Switched model to: {args.strip()}")

    async def _cmd_compact(self):
        self._print("Compacting memory…")
        try:
            await self._memory.check_and_summarize()
            self._print("Memory compacted.")
        except Exception as e:
            self._print(f"Compaction failed: {e}")

    async def _cmd_settings(self, args: str):
        if not args:
            keys = ["provider.active", "ui.theme", "voice.engine", "profile"]
            self._print("Key settings:\n" + _format_settings_table(self._settings, keys))
            self._print("Use /settings <key> <val> to set a value.")
            return
        parts = args.strip().split(" ", 1)
        key = parts[0]
        val = parts[1] if len(parts) > 1 else None
        if val:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self._settings.set(key, val)
            )
            self._reload_settings()
            self._print(f"Set {key} = {val}")
        else:
            v = self._settings.get(key, "not set")
            self._print(f"{key} = {v}")

    async def _cmd_memory(self):
        sessions = self._memory.get_sessions()
        current = self._memory.get_current_session()
        total_msgs = sum(s.get("message_count", 0) for s in sessions)
        self._print(
            f"Sessions:         {len(sessions)}\n"
            f"Total messages:   {total_msgs}\n"
            f"Current session:  {current}"
        )

    async def _cmd_stats(self):
        try:
            from backend.core.metrics import get_collector
            collector = get_collector()
            r = await collector.report(days=7)
            self._print(
                f"Turns:        {r['total_turns']}\n"
                f"Cost:         ${r['total_cost_usd']:.4f} USD\n"
                f"Tokens:       {r['total_tokens']:,}\n"
                f"Avg latency:  {r['avg_latency_ms']:.0f} ms\n"
                f"Tool calls:   {r['total_tool_calls']}"
            )
        except Exception as e:
            self._print(f"Stats unavailable: {e}")

    async def _cmd_theme(self, args: str):
        if not args or args.strip().lower() not in _VALID_THEMES:
            current = self._settings.get("ui.theme", "dark")
            valid = ", ".join(sorted(_VALID_THEMES))
            self._print(f"Current theme: {current}\nValid themes: {valid}")
            return
        theme = args.strip().lower()
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: self._settings.set("ui.theme", theme)
        )
        self._print(f"Theme switched to: {theme}")

    async def _cmd_character(self, args: str):
        from backend.core.paths import CHARACTERS_DIR
        if not args:
            current = self._settings.get("character.active", "default")
            self._print(f"Current character: {current}")
            return
        name = args.strip()
        char_dir = str(CHARACTERS_DIR / name)
        if os.path.isdir(char_dir):
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self._settings.set("character.active", name)
            )
            self._print(f"Loaded character: {name}")
        else:
            chars = [d for d in os.listdir(str(CHARACTERS_DIR))
                     if os.path.isdir(os.path.join(str(CHARACTERS_DIR), d))]
            self._print(f"Character '{name}' not found.\nAvailable: {', '.join(chars)}")

    async def _cmd_profile(self, args: str):
        if not args:
            current = self._settings.get("profile", "default")
            self._print(f"Current profile: {current}")
            return
        name = args.strip()
        if name not in _VALID_PROFILES:
            self._print(f"Invalid profile: {name}\nValid: {', '.join(_VALID_PROFILES)}")
            return
        from backend.core.config.settings import switch_profile
        try:
            switch_profile(name)
            self._reload_settings()
            self._print(f"Profile switched to: {name}")
        except ValueError as e:
            self._print(f"Error: {e}")

    async def _cmd_think(self):
        self._show_thinking = not self._show_thinking
        self._print(f"Thinking display: {'ON' if self._show_thinking else 'OFF'}")

    async def _cmd_companion(self, args: str):
        if args.strip().lower() == "on":
            self._companion_enabled = True
            self._print("Companion mode ON — I'll send idle prompts when quiet.")
            self._start_idle_loop()
        elif args.strip().lower() == "off":
            self._companion_enabled = False
            self._stop_idle_loop()
            self._print("Companion mode OFF.")
        else:
            self._print(f"Companion mode: {'ON' if self._companion_enabled else 'OFF'}\nUsage: /companion on|off")

    async def _cmd_approve(self, args: str):
        if not args:
            self._print("Usage: /approve <tool_name>")
            return
        mcp = self._shared.get("mcp")
        if mcp and hasattr(mcp, 'approve_tool'):
            mcp.approve_tool(args.strip())
            self._print(f"Approved tool: {args.strip()}")
        else:
            self._print("MCP client not available for approval.")

    async def _cmd_permission(self, args: str):
        valid = {"readonly", "confirm", "full"}
        if not args or args.strip().lower() not in valid:
            self._print(f"Usage: /permission [{'|'.join(valid)}]")
            return
        level = args.strip().lower()
        mcp = self._shared.get("mcp")
        if mcp and hasattr(mcp, 'set_permission_level'):
            mcp.set_permission_level(level)
            self._print(f"Permission level set to: {level}")
        else:
            self._print(f"Permission level changed to {level} (local only).")

    # ── idle companion loop ─────────────────────────────────────────────

    def _start_idle_loop(self):
        self._stop_idle_loop()
        self._idle_task = asyncio.create_task(self._idle_loop())

    def _stop_idle_loop(self):
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    async def _idle_loop(self):
        """Every 30s of inactivity, generate a proactive idle prompt."""
        try:
            while self._companion_enabled:
                await asyncio.sleep(30)
                if not self._companion_enabled:
                    break
                prompt = await self._agent.generate_idle_prompt()
                if prompt:
                    print(f"\n[companion] {prompt}")
        except asyncio.CancelledError:
            pass

    # ── main loop ────────────────────────────────────────────────────────

    async def run(self):
        _print_banner()
        sid = self._memory.get_current_session()
        self._print(f"Session: {sid}")
        self._print("Ready. Type your message or /command.\n")

        while True:
            try:
                raw = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not raw:
                continue

            # ── slash command ────────────────────────────────────────────
            if raw.startswith("/"):
                cmd_line = raw[1:].strip()
                parts = cmd_line.split(maxsplit=1)
                cmd = parts[0].lower() if parts else ""
                args = parts[1] if len(parts) > 1 else ""

                dispatch = {
                    "help": self._cmd_help,
                    "quit": None, "exit": None, "q": None,
                    "clear": self._cmd_clear,
                    "new": self._cmd_new,
                    "rename": self._cmd_rename,
                    "export": self._cmd_export,
                    "sessions": self._cmd_sessions,
                    "session": self._cmd_session,
                    "status": self._cmd_status,
                    "provider": self._cmd_provider,
                    "model": self._cmd_model,
                    "compact": self._cmd_compact,
                    "settings": self._cmd_settings,
                    "memory": self._cmd_memory,
                    "stats": self._cmd_stats,
                    "theme": self._cmd_theme,
                    "character": self._cmd_character,
                    "profile": self._cmd_profile,
                    "think": self._cmd_think,
                    "companion": self._cmd_companion,
                    "approve": self._cmd_approve,
                    "permission": self._cmd_permission,
                }

                if cmd in ("quit", "exit", "q"):
                    self._stop_idle_loop()
                    print("Goodbye!")
                    break

                handler = dispatch.get(cmd)
                if handler:
                    if args is not None and cmd in ("rename", "export", "session", "settings",
                                                     "provider", "model", "theme", "character",
                                                     "profile", "approve", "permission", "companion"):
                        await handler(args)
                    elif cmd == "think":
                        await handler()
                    elif cmd in ("sessions", "status", "compact", "memory", "stats", "clear", "new"):
                        await handler()
                    elif cmd == "help":
                        await handler()
                    else:
                        await handler(args)
                else:
                    self._print(f"Unknown command: /{cmd}. Try /help.")
                continue

            # ── normal message → agent ───────────────────────────────────
            self._print("")
            try:
                async for chunk in self._agent.handle_user_input(raw):
                    if isinstance(chunk, str):
                        print(chunk, end="", flush=True)
                    elif isinstance(chunk, tuple):
                        sig_type, sig_val = chunk
                        if sig_type == "__thinking__" and self._show_thinking:
                            print(f"\n[thinking: {sig_val}]\n", end="", flush=True)
                        elif sig_type == "__tool__":
                            print(f"\n[tool: {sig_val}]", end="", flush=True)
                        elif sig_type == "__error__":
                            print(f"\n[Error: {sig_val}]", end="", flush=True)
                        elif sig_type == "__emotion__":
                            pass  # silent in CLI
                        elif sig_type == "__expression__":
                            pass
                        elif sig_type == "__roleplay__":
                            print(f" *{sig_val}* ", end="", flush=True)
                print()
            except Exception as e:
                print(f"\n[Error: {e}]")


def main():
    """Entry point for python -m backend.cli.companion"""
    asyncio.run(CompanionREPL().run())


if __name__ == "__main__":
    main()
