"""
CLI mode — interactive terminal interface for the agent.
Runs in-process (direct) or connects to a remote gRPC server.

Usage:
  python main.py cli                         # In-process agent (interactive)
  python main.py cli --grpc                  # Remote gRPC agent
  python main.py cli --provider openai       # Pick provider at launch
  python main.py cli --model gpt-4o          # Pick model at launch
  python main.py cli --resume <session_id>   # Resume a saved session
  python main.py cli serve                   # Start gRPC server daemon
  python main.py cli stop                    # Stop running daemon
  python main.py cli status                  # Show daemon + service status
  python main.py cli run "hello world"       # One-shot: send message, print response, exit
  python main.py cli run "hello" --json      # One-shot with JSON output
  python main.py cli run "hello" --ndjson    # One-shot with NDJSON streaming
  python main.py cli login <provider>        # Interactive OAuth login
  python main.py cli login-status            # Show configured providers
  python main.py cli auth                    # Consolidated auth status
  python main.py cli --check                 # Pre-flight diagnostics
  python main.py cli --version               # Show version
  python main.py cli --json                  # Machine-readable JSON output
"""
import asyncio
import argparse
import difflib
import logging
import os
import sys
import json
import signal
import time

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import FuzzyWordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.shortcuts import clear

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
if "HF_TOKEN" not in os.environ:
    os.environ["HF_TOKEN"] = ""

log = logging.getLogger(__name__)
VERSION = "0.2.0"  # bumped for the refactored release
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_HISTFILE = str(_DATA_DIR / ".repl_history")
_CRASH_FILE = os.path.join(os.path.expanduser("~"), ".amalgam", "crash_state.json")
_SNAPSHOT_FILE = os.path.join(os.path.expanduser("~"), ".amalgam", "last_session.json")
_CLI_ARGS = None  # populated by main() before entering interactive mode

# ── Import sub-modules ──────────────────────────────────────────────────
from cli.output import (
    set_output_format, wants_human, wants_json,
    message as out_msg, error as out_err, table as out_table,
    panel as out_panel, markup as out_markup, banner as out_banner,
    human_status, human_markup, human_error, human_table,
    human_panel, OutputFormat,
)
from cli.provider import (
    KNOWN_PROVIDERS, PROVIDER_MODELS,
    detect_providers, resolve_display_name, autocomplete_words,
)
import cli.server as daemon
import cli.auth as auth_mod

_COMMANDS = [
    "/character", "/clear", "/compact", "/companion", "/crash", "/exit",
    "/health", "/help", "/memory", "/model", "/new", "/permission",
    "/profile", "/provider", "/quit", "/rename", "/resume", "/retry",
    "/session", "/sessions", "/settings", "/stats", "/status", "/theme",
    "/think",
]


def _make_console():
    from rich.console import Console
    return Console()


def _show_banner(console, session_id, provider, model, title=None, health=None):
    """Legacy banner (Rich console). For --json, use out_banner()."""
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    grid = Table.grid(padding=1)
    grid.add_column(style="cyan")
    grid.add_column()
    grid.add_row("Session", f"[bold]{title or session_id[:16]}[/bold]")
    grid.add_row("Provider", provider)
    grid.add_row("Model", model)

    if health is not None and health:
        dots = []
        for name, status in sorted(health.items()):
            color = {"ok": "green", "degraded": "yellow", "down": "red",
                     "not_configured": "dim", "unknown": "dim"}.get(status, "dim")
            dots.append(f"[{color}]{name}:{status}[/{color}]")
        grid.add_row("Services", "  ".join(dots))

    console.print(Panel(grid, title="[bold yellow]Amalgam[/bold yellow]", border_style="yellow"))
    console.print("[dim]Type /exit to quit, /new for new session, /help for commands[/dim]\n")


def _suppress_logs():
    """Silence common library logs for CLI mode."""
    loggers = [
        "huggingface_hub", "huggingface_hub.utils._http", "urllib3", "httpx",
        "httpcore", "chromadb", "asyncio", "mcp.os.posix.utilities",
        "backend.core.llm.litellm_provider", "backend.core.memory.manager",
        "litellm", "aiosqlite", "vaderSentiment", "faster_whisper", "edge-tts"
    ]
    for name in loggers:
        logging.getLogger(name).setLevel(logging.CRITICAL)

    logging.getLogger().setLevel(logging.CRITICAL)
    for name in logging.root.manager.loggerDict:
        logger = logging.getLogger(name)
        logger.setLevel(logging.CRITICAL)
        logger.handlers.clear()
        logger.propagate = False

    logging.getLogger().handlers.clear()
    os.environ["LOG_LEVEL"] = "CRITICAL"


def _extract_error_message(error_str: str) -> str:
    """Try to extract a human-readable message from an error."""
    import re
    clean = re.sub(r'^litellm\.\w+Error:\s*', '', error_str)
    clean = re.sub(r'^\w+Exception\s*-\s*', '', clean)
    try:
        match = re.search(r'\{.*\}', clean)
        if match:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                if "error" in data and isinstance(data["error"], dict):
                    msg = data["error"].get("message", "")
                    if msg:
                        return msg
                msg = data.get("message", data.get("error", ""))
                if msg:
                    return str(msg)
    except Exception:
        pass
    clean = clean.split("\n")[0].strip()
    if len(clean) > 300:
        clean = clean[:300] + "..."
    return clean


def _categorize_error(error_str: str) -> dict:
    """Categorize an error and return recovery hints."""
    lowered = error_str.lower()
    info: dict = {"category": "unknown", "hint": "", "auto_health": False}

    if any(x in lowered for x in [
        "refused", "connection refused", "connection reset",
        "timeout", "timed out", "connect failed",
        "econnrefused", "econnreset", "no route to host",
        "connectionerror", "cannot connect",
    ]):
        info["category"] = "connection"
        info["hint"] = "Is the provider service running? Check your network and base URL."
        info["diagnostic"] = "python main.py cli --check"

    elif any(x in lowered for x in [
        "401", "403", "unauthorized", "forbidden",
        "invalid key", "api key", "authentication", "auth",
        "invalid_api_key", "permission denied",
    ]):
        info["category"] = "auth"
        info["hint"] = "Your API key may be invalid. Use /provider to switch or run 'cli login <provider>'."
        info["auto_health"] = True

    elif any(x in lowered for x in [
        "rate limit", "rate_limit", "429",
        "too many requests", "quota exceeded", "rate exceeded",
    ]):
        info["category"] = "rate_limit"
        info["hint"] = "Rate limited. Wait a moment and try again."

    elif any(x in lowered for x in [
        "model not found", "model_not_found",
        "not found", "model unavailable",
        "not supported", "does not exist",
        "unavailable", "not_found", "model not supported",
    ]):
        info["category"] = "model"
        info["hint"] = "Model not found or unavailable. Use /model to switch."
        info["auto_health"] = True

    else:
        info["hint"] = "Fix the model or provider and try again."

    return info


def _fuzzy_command_suggestion(bad_cmd: str) -> str | None:
    """Find closest matching command using difflib.get_close_matches."""
    matches = difflib.get_close_matches(bad_cmd, _COMMANDS, n=1, cutoff=0.5)
    return matches[0] if matches else None


async def _get_session_title(memory, sid):
    """Get session title using public API (get_sessions)."""
    try:
        for s in memory.get_sessions():
            if s.get("id") == sid:
                return s.get("title") or s.get("id", sid)[:16]
    except Exception:
        pass
    return sid[:16]


async def _refresh_banner(con, memory, settings):
    """Re-draw banner with current state."""
    sid = memory.get_current_session()
    title = await _get_session_title(memory, sid)
    active = settings.get("provider.active", "?")
    model = settings.get(f"provider.{active}.model", "?")

    health = None
    try:
        from backend.core.health import get_registry
        registry = get_registry()
        results = await registry.check_all()
        health = {n: s["status"] for n, s in results.items()} if results else None
    except Exception:
        try:
            from backend.core.health import get_registry
            health = get_registry().get_all()
            health = {n: s["status"] for n, s in health.items()} if health else None
        except Exception:
            pass

    if wants_json():
        out_banner(sid, active, model, title=title, health=health)
    else:
        clear()
        _show_banner(con, sid, active, model, title=title, health=health)


def _save_history():
    """Write readline history to file."""
    import readline
    try:
        if not os.path.exists(os.path.dirname(_HISTFILE)):
            os.makedirs(os.path.dirname(_HISTFILE), exist_ok=True)
        readline.write_history_file(_HISTFILE)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# Crash recovery
# ═══════════════════════════════════════════════════════════════════════

def _save_crash_state(session_id: str, provider: str, model: str,
                      last_message: str = "") -> None:
    """Record crash/abnormal-exit state for next launch."""
    try:
        os.makedirs(os.path.dirname(_CRASH_FILE), exist_ok=True)
        with open(_CRASH_FILE, "w") as f:
            json.dump({
                "session_id": session_id,
                "provider": provider,
                "model": model,
                "last_message": last_message,
                "timestamp": time.time(),
            }, f)
    except Exception:
        pass


def _clear_crash_state() -> None:
    """Remove crash state (called on clean exit)."""
    try:
        os.remove(_CRASH_FILE)
    except OSError:
        pass


def _check_crash_recovery(console) -> str | None:
    """Check for crash state from a previous run.

    Returns the last session ID if recovery is available, else None.
    Prints recovery info to console.
    """
    try:
        if not os.path.exists(_CRASH_FILE):
            return None
        with open(_CRASH_FILE) as f:
            state = json.load(f)
        sid = state.get("session_id", "")
        provider = state.get("provider", "?")
        model = state.get("model", "?")
        last_msg = state.get("last_message", "")
        ts = state.get("timestamp", 0)

        if ts:
            ago = time.time() - ts
            time_str = f"{ago:.0f}s ago" if ago < 120 else f"{ago/60:.0f}m ago"
        else:
            time_str = "recently"

        # Show crash banner
        from rich.panel import Panel
        lines = [
            "[red]The last session ended unexpectedly.[/red]",
            f"[dim]Session: {sid[:16]}[/dim]",
            f"[dim]Provider: {provider} | Model: {model}[/dim]",
            f"[dim]Crashed {time_str}[/dim]",
        ]
        if last_msg:
            lines.append(f"\n[dim]Last message: {last_msg[:80]}[/dim]")
        lines.append(f"\n[yellow]→ Type /resume to recover, or /new for a fresh start[/yellow]")

        console.print(Panel(
            "\n".join(lines),
            title="[bold yellow]Crash Recovery[/bold yellow]",
            border_style="yellow",
        ))
        return sid
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# Session snapshot
# ═══════════════════════════════════════════════════════════════════════

def _save_snapshot(session_id: str, provider: str, model: str) -> None:
    """Save session snapshot for restore across restarts."""
    try:
        os.makedirs(os.path.dirname(_SNAPSHOT_FILE), exist_ok=True)
        with open(_SNAPSHOT_FILE, "w") as f:
            json.dump({
                "session_id": session_id,
                "provider": provider,
                "model": model,
                "timestamp": time.time(),
            }, f)
    except Exception:
        pass


def _load_snapshot() -> dict | None:
    """Load the last saved session snapshot."""
    try:
        if os.path.exists(_SNAPSHOT_FILE):
            with open(_SNAPSHOT_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════
# Health / diagnostics
# ═══════════════════════════════════════════════════════════════════════

async def _run_check(verbose=False) -> bool:
    """Pre-flight diagnostics. Returns True if all healthy."""
    from rich.console import Console
    con = Console()
    con.print()
    con.print("[bold]=== Service Diagnostics ===[/bold]")
    con.print()

    from backend.core.deps import get_shared
    from backend.core.health import get_registry, register_builtin_checks

    shared = get_shared()
    s = shared.get("settings")

    register_builtin_checks(
        settings_obj=s,
        llm_obj=shared.get("llm"),
        tts_obj=shared.get("tts"),
    )

    registry = get_registry()
    results = await registry.check_all()
    all_ok = True

    for name in sorted(results.keys()):
        state = results[name]
        status = state.get("status", "unknown")
        latency = state.get("latency_ms", 0)
        detail = state.get("detail", "")

        if status == "ok":
            color = "green"
            prefix = "\u2713"
        elif status == "degraded":
            color = "yellow"
            prefix = "\u26a0"
        elif status in ("down",):
            color = "red"
            prefix = "\u2717"
            all_ok = False
        else:
            color = "dim"
            prefix = "\u00b7"

        lat_str = f" ({latency:.0f}ms)" if latency else ""
        con.print(f"  [{color}]{prefix} {name:15s} {status}{lat_str}[/{color}]")
        if verbose and detail:
            con.print(f"    {'':15s}[dim]{detail}[/dim]")
        if status != "ok" and verbose and state.get("last_error"):
            con.print(f"    {'':15s}[red]{state['last_error']}[/red]")

    con.print()
    ok_count = sum(1 for s in results.values() if s.get("status") == "ok")
    total = len(results)
    if ok_count == total:
        con.print(f"[green]\u2713 All {total} services healthy[/green]")
    else:
        con.print(f"[red]\u2717 {total - ok_count}/{total} services unhealthy[/red]")
    return all_ok


# ═══════════════════════════════════════════════════════════════════════
# Main CLI loop (direct in-process)
# ═══════════════════════════════════════════════════════════════════════

async def run_cli_direct():
    """Run the agent directly in-process (no gRPC needed)."""
    _suppress_logs()

    from backend.core.startup import init_application, shutdown_application
    await init_application()

    # Re-suppress now that configure_logging has been called
    _suppress_logs()

    from backend.core.deps import get_shared

    shared = get_shared()
    agent = shared["agent"]
    memory = shared["memory"]
    settings = shared["settings"]
    llm = shared["llm"]
    
    # Mark this session as CLI/TUI mode so backend uses appropriate STT engine
    try:
        settings.set("ui.mode", "tui")
    except Exception:
        pass
    _last_message = [""]
    _show_thinking = [True]

    # Apply --provider, --model, --resume from CLI args
    if _CLI_ARGS:
        _apply_cli_settings(settings, llm, memory, _CLI_ARGS)

    con = _make_console()

    # ── Crash recovery check ──────────────────────────────────────────
    crash_sid = _check_crash_recovery(con)

    # ── Initial banner ────────────────────────────────────────────────
    sid = memory.get_current_session()
    title = await _get_session_title(memory, sid)
    active = settings.get("provider.active", "?")
    model = settings.get(f"provider.{active}.model", "?")

    # If crash recovery found a session, offer to switch to it
    if crash_sid and crash_sid != sid:
        from rich.prompt import Confirm
        if Confirm.ask(f"\nSwitch to crashed session {crash_sid[:16]}?", default=True):
            try:
                memory.set_current_session(crash_sid)
                sid = crash_sid
                title = await _get_session_title(memory, sid)
            except Exception:
                pass

    health = None
    try:
        from backend.core.health import get_registry
        registry = get_registry()
        results = await registry.check_all()
        health = {n: s["status"] for n, s in results.items()} if results else None
    except Exception:
        pass

    # Print banner
    if wants_json():
        out_banner(sid, active, model, title=title, health=health)
    else:
        clear()
        _show_banner(con, sid, active, model, title=title, health=health)

    def _build_completer():
        # Only complete command names (the first word).
        # Do NOT use WORD=True — that would enable per-word completion
        # inside multi-word input, which causes prompt_toolkit to mangle
        # the buffer on Enter (wiping the command prefix).
        return FuzzyWordCompleter(_COMMANDS)

    prompt_session = PromptSession(history=FileHistory(_HISTFILE), completer=_build_completer())

    # ── Save snapshot on start ────────────────────────────────────────
    _save_snapshot(sid, active, model)

    # ── Signal handler for crash recovery ─────────────────────────────
    def _crash_handler(signum, frame):
        try:
            _save_crash_state(
                memory.get_current_session(),
                settings.get("provider.active", "?"),
                settings.get(f"{settings.get('provider.active', '?')}.model", "?"),
                _last_message[0],
            )
        except Exception:
            pass
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, _crash_handler)
    signal.signal(signal.SIGINT, signal.default_int_handler)  # Keep Ctrl+C normal

    try:
        while True:
            try:
                text = await prompt_session.prompt_async("> ")
                text = text.strip()
            except EOFError:
                con.print()
                break
            except KeyboardInterrupt:
                con.print()
                continue

            if not text:
                continue

            # ── Commands ──────────────────────────────────────────────
            if text == "/exit":
                break

            elif text == "/new":
                session_id = memory.start_session()
                await _refresh_banner(con, memory, settings)
                continue

            elif text == "/help":
                from rich.table import Table
                from rich import box
                tbl = Table(box=box.SIMPLE, show_header=False)
                tbl.add_column("Command", style="cyan")
                tbl.add_column("Description")
                for row in [
                    ("/clear", "Clear terminal and reprint banner"),
                    ("/compact", "Force memory compaction"),
                    ("/companion [on|off]", "Toggle, enable, or disable companion mode (voice + avatar)"),
                    ("/crash", "Simulate a crash (for testing recovery)"),
                    ("/exit", "Quit the CLI"),
                    ("/health", "Show live service health report"),
                    ("/model <name>", "Switch model for current provider"),
                    ("/new", "Start a new session and clear screen"),
                    ("/provider <name>", "Switch AI provider"),
                    ("/rename <title>", "Rename the current session"),
                    ("/resume", "Show last 5 turns"),
                    ("/retry", "Retry your last message"),
                    ("/session", "Show current session ID"),
                    ("/sessions", "List or switch sessions (prefix match)"),
                    ("/status", "Show provider, model, session info"),
                    ("/think [on|off]", "Toggle, enable, or disable thinking display"),
                ]:
                    tbl.add_row(*row)
                con.print(tbl)
                continue

            elif text == "/companion" or text.startswith("/companion "):
                parts = text.split(maxsplit=1)
                arg = parts[1].lower() if len(parts) > 1 else ""
                if arg == "on":
                    new_state = True
                elif arg == "off":
                    new_state = False
                elif arg == "":
                    new_state = not settings.get("voice.input_enabled", False)
                else:
                    con.print("[red]Usage: /companion [on|off][/red]")
                    continue
                settings.set("voice.input_enabled", new_state)
                settings.set("voice.output_enabled", new_state)
                con.print(f"[green]Companion mode ON[/green]" if new_state else "[red]Companion mode OFF[/red]")
                continue

            elif text == "/think" or text.startswith("/think "):
                parts = text.split(maxsplit=1)
                arg = parts[1].lower() if len(parts) > 1 else ""
                if arg == "on":
                    new_state = True
                elif arg == "off":
                    new_state = False
                elif arg == "":
                    new_state = not _show_thinking[0]
                else:
                    con.print("[red]Usage: /think [on|off][/red]")
                    continue
                _show_thinking[0] = new_state
                con.print(f"[green]Thinking display: ON[/green]" if new_state else "[red]Thinking display: OFF[/red]")
                continue

            elif text == "/clear":
                await _refresh_banner(con, memory, settings)
                continue

            elif text == "/session":
                if wants_json():
                    json.dump({"type": "session", "session_id": memory.get_current_session()}, sys.stdout, default=str)
                    print()
                else:
                    con.print(f"[cyan]Session:[/cyan] {memory.get_current_session()}")
                continue

            elif text == "/sessions" or text.startswith("/sessions "):
                parts = text.split(maxsplit=1)
                if len(parts) == 1:
                    current_id = memory.get_current_session()
                    all_sessions = memory.get_sessions()
                    if not all_sessions:
                        con.print("[yellow]No sessions found.[/yellow]")
                        continue
                    if wants_json():
                        out_table(
                            [(s.get("id","?"), s.get("title",""), str(s.get("message_count",0)))
                             for s in all_sessions],
                            headers=["ID", "Title", "Messages"],
                        )
                    else:
                        from rich.table import Table
                        from rich import box
                        tbl = Table(box=box.SIMPLE, show_header=True)
                        tbl.add_column("", style="dim", width=9)
                        tbl.add_column("ID", style="cyan", no_wrap=True)
                        tbl.add_column("Title", style="white")
                        tbl.add_column("Messages", justify="right", style="green")
                        for s in all_sessions:
                            sid = s.get("id", "?")
                            title = s.get("title") or ""
                            msg_count = s.get("message_count", 0)
                            marker = "[yellow]\u25b6 current[/yellow]" if sid == current_id else ""
                            short_id = sid[:20] + "\u2026" if len(sid) > 20 else sid
                            tbl.add_row(marker, short_id, title, str(msg_count))
                        con.print(tbl)
                else:
                    prefix = parts[1]
                    current_id = memory.get_current_session()
                    all_sessions = memory.get_sessions()
                    matches = [s for s in all_sessions if s.get("id", "").startswith(prefix)]
                    if len(matches) == 0:
                        con.print(f"[red]No session found with ID prefix:[/red] {prefix}")
                        all_ids = [s.get("id", "") for s in all_sessions if s.get("id")]
                        sid_suggestions = difflib.get_close_matches(prefix, all_ids, n=3, cutoff=0.4)
                        if sid_suggestions:
                            display = [s[:20] + "…" if len(s) > 20 else s for s in sid_suggestions]
                            con.print(f"[dim]Did you mean: {', '.join(display)}[/dim]")
                    elif len(matches) > 1:
                        ids = ", ".join(s.get("id", "")[:16] + "\u2026" for s in matches)
                        con.print(f"[red]Ambiguous prefix '{prefix}' matches:[/red] {ids}")
                    else:
                        target_id = matches[0]["id"]
                        if target_id == current_id:
                            con.print(f"[yellow]Already on session:[/yellow] {target_id[:20]}")
                        else:
                            memory.set_current_session(target_id)
                            con.print(f"[green]Switched to session:[/green] {target_id[:20]}")
                            await _refresh_banner(con, memory, settings)
                continue

            elif text == "/health":
                try:
                    from backend.core.health import get_registry
                    registry = get_registry()
                    results = await registry.check_all()
                    if results:
                        if wants_json():
                            out_table(
                                [(n, s.get("status","?"), s.get("detail",""))
                                 for n, s in sorted(results.items())],
                                headers=["Service", "Status", "Detail"],
                            )
                        else:
                            from rich.table import Table
                            from rich import box
                            tbl = Table(box=box.SIMPLE, show_header=True)
                            tbl.add_column("Service", style="cyan")
                            tbl.add_column("Status")
                            tbl.add_column("Detail")
                            for name, s in sorted(results.items()):
                                st = s.get("status", "?")
                                color = {"ok": "green", "degraded": "yellow",
                                         "down": "red", "not_configured": "dim",
                                         "unknown": "dim"}.get(st, "dim")
                                tbl.add_row(name, f"[{color}]{st}[/{color}]",
                                            f"[dim]{s.get('detail', '')}[/dim]")
                            con.print(tbl)
                    else:
                        con.print("[yellow]No health data available[/yellow]")
                except Exception as e:
                    con.print(f"[red]Health check failed: {e}[/red]")
                continue

            elif text == "/status":
                active = settings.get("provider.active", "?")
                model = settings.get(f"provider.{active}.model", "?")
                if wants_json():
                    out_table([
                        ("Provider", active),
                        ("Model", model),
                        ("Session", memory.get_current_session()),
                    ])
                else:
                    from rich.table import Table
                    from rich import box
                    tbl = Table(box=box.SIMPLE, show_header=False)
                    tbl.add_column("Key", style="cyan")
                    tbl.add_column("Value")
                    tbl.add_row("Provider", active)
                    tbl.add_row("Model", model)
                    tbl.add_row("Session", memory.get_current_session())

                    try:
                        from backend.core.health import get_registry
                        registry = get_registry()
                        results = await registry.check_all()
                        if results:
                            statuses = ", ".join(
                                f"{n}:{s.get('status', '?')}" for n, s in sorted(results.items())
                            )
                            tbl.add_row("Services", statuses)
                    except Exception:
                        pass
                    con.print(tbl)
                continue

            elif text == "/compact":
                with con.status("[yellow]Compacting memory...[/yellow]"):
                    await memory.check_and_summarize()
                con.print("[green]Memory compacted.[/green]")
                continue

            elif text.startswith("/rename"):
                parts = text.split(maxsplit=1)
                if len(parts) > 1:
                    sid = memory.get_current_session()
                    try:
                        new_title = await memory.rename_session(sid, parts[1])
                        con.print(f"[green]Session renamed to:[/green] {new_title}")
                        await _refresh_banner(con, memory, settings)
                    except ValueError as e:
                        con.print(f"[red]Error:[/red] {e}")
                continue

            elif text == "/resume":
                sid = memory.get_current_session()
                turns = memory.get_session_turns(sid, turns=5)
                con.print(f"[cyan]Resuming last 5 turns of {sid}:[/cyan]")
                for turn in turns:
                    con.print(f"[bold]{turn['role'].upper()}:[/bold] {turn['content']}")
                continue

            elif text == "/provider" or text.startswith("/provider "):
                parts = text.split(maxsplit=2)
                if len(parts) > 2:
                    subcmd = parts[1].lower()
                    name = parts[2]
                    if subcmd == "set":
                        settings.set("provider.active", name)
                        con.print(f"[green]Provider set to {name}[/green]")
                    elif subcmd == "add":
                        from cli.auth import login_provider as _cli_login
                        _cli_login(settings, name)
                    elif subcmd == "rm":
                        cfg = settings.get(f"provider.{name}")
                        if isinstance(cfg, dict) and cfg.get("api_key"):
                            del cfg["api_key"]
                            settings.set(f"provider.{name}", cfg)
                            con.print(f"[green]API key removed for {name}[/green]")
                        else:
                            con.print(f"[yellow]No API key found for {name}[/yellow]")
                    else:
                        suggestions = difflib.get_close_matches(subcmd, ["set", "add", "rm"], n=1, cutoff=0.4)
                        if suggestions:
                            con.print(f"[dim]Did you mean: [italic]{suggestions[0]}[/italic]?[/dim]")
                        con.print(f"[red]Unknown subcommand: {subcmd}. Use: set, add, rm[/red]")
                elif len(parts) > 1:
                    new_provider = parts[1]
                    if new_provider not in KNOWN_PROVIDERS:
                        con.print(f"[red]Unknown provider:[/red] {new_provider}")
                        con.print(f"[dim]Known providers: {', '.join(KNOWN_PROVIDERS)}[/dim]")
                        prov_suggestions = difflib.get_close_matches(new_provider, KNOWN_PROVIDERS, n=1, cutoff=0.4)
                        if prov_suggestions:
                            con.print(f"[dim]Did you mean: [italic]{prov_suggestions[0]}[/italic]?[/dim]")
                        con.print("[yellow]Setting anyway (providers are not gatekept)...[/yellow]")
                    settings.set("provider.active", new_provider)
                    llm.reload_settings()
                    prompt_session.completer = _build_completer()
                    await _refresh_banner(con, memory, settings)
                else:
                    con.print(f"Current provider: {settings.get('provider.active')}")
                continue

            elif text.startswith("/model"):
                provider = settings.get("provider.active", "gemini")
                from cli.provider import resolve_display_name
                _rev_map = {"chatgpt": "openai", "claude": "anthropic"}
                model_key = _rev_map.get(provider, provider)
                parts = text.split(maxsplit=1)
                if len(parts) > 1:
                    new_model = parts[1]
                    known_models = PROVIDER_MODELS.get(model_key, [])
                    if known_models:
                        if new_model in known_models:
                            con.print(f"[green]\u2713[/green] {new_model} is a known model for {provider}")
                        else:
                            con.print(f"[yellow]Warning:[/yellow] '{new_model}' not in known list for {provider}")
                            con.print(f"[dim]Known: {', '.join(known_models)}[/dim]")
                            model_suggestions = difflib.get_close_matches(new_model, known_models, n=1, cutoff=0.4)
                            if model_suggestions:
                                con.print(f"[dim]Did you mean: [italic]{model_suggestions[0]}[/italic]?[/dim]")
                    else:
                        con.print(f"[dim]No known models list for {provider}; accepting {new_model}[/dim]")
                    settings.set(f"provider.{provider}.model", new_model)
                    llm.reload_settings()
                    await _refresh_banner(con, memory, settings)
                else:
                    current = settings.get(f"provider.{provider}.model", "?")
                    con.print(f"Current model: {current}")
                    known = PROVIDER_MODELS.get(provider, [])
                    if known:
                        con.print(f"[dim]Known models: {', '.join(known)}[/dim]")
                continue

            elif text == "/crash":
                # Simulate a crash (for testing recovery)
                con.print("[red]Simulating crash for testing recovery...[/red]")
                _save_crash_state(
                    memory.get_current_session(),
                    settings.get("provider.active", "?"),
                    settings.get(f"{settings.get('provider.active', '?')}.model", "?"),
                    _last_message[0],
                )
                con.print("[red]Crash state saved. Exiting...[/red]")
                # Use os._exit to skip the finally block that clears crash state
                _save_history()
                os._exit(0)

            # ── Retry last message ───────────────────────────────────
            if text == "/retry":
                if not _last_message[0]:
                    con.print("[dim]No previous message to retry.[/dim]")
                    continue
                con.print(f"[dim]Retrying: {_last_message[0]}[/dim]")
                text = _last_message[0]

            # ── Unknown command ───────────────────────────────────────
            elif text.startswith("/"):
                suggestion = _fuzzy_command_suggestion(text)
                if suggestion:
                    con.print(f"[red]Unknown command:[/red] {text}")
                    con.print(f"[dim]Did you mean:[/dim] [italic]{suggestion}[/italic]?")
                else:
                    con.print(f"[red]Unknown command:[/red] {text}")
                continue

            # ── Chat with agent ───────────────────────────────────────
            from rich.panel import Panel
            _last_message[0] = text

            # Save snapshot on each message
            _save_snapshot(
                memory.get_current_session(),
                settings.get("provider.active", "?"),
                settings.get(f"{settings.get('provider.active', '?')}.model", "?"),
            )

            try:
                async for chunk in agent.handle_user_input(text):
                    if isinstance(chunk, tuple):
                        tag_type, tag_val = chunk
                        if tag_type == "__thinking__":
                            if _show_thinking[0]:
                                con.print(f"[dim]\\[thinking] {tag_val}[/dim]")
                        elif tag_type == "__roleplay__":
                            con.print(f"[yellow]* {tag_val} *[/yellow]")
                        elif tag_type == "__tool__":
                            con.print(Panel(
                                f"[cyan]{tag_val}[/cyan]",
                                title="[bold cyan]Tool[/bold cyan]",
                                border_style="cyan"
                            ))
                        elif tag_type == "__permission__":
                            from rich.prompt import Prompt
                            con.print(Panel(
                                f"[yellow]{tag_val}[/yellow]",
                                title="[bold yellow]Permission Needed[/bold yellow]",
                                border_style="yellow"
                            ))
                            action = Prompt.ask(
                                "  Options",
                                choices=["once", "prefix", "exact", "deny"],
                                default="deny"
                            )
                            con.print(f"  {action}")
                        elif tag_type == "__error__":
                            msg = _extract_error_message(tag_val)
                            con.print(Panel(
                                f"[red]{msg}[/red]",
                                title="[bold red]Error[/bold red]",
                                border_style="red"
                            ))
                    else:
                        con.print(chunk, end="")
                con.print()
            except Exception as e:
                from rich.panel import Panel
                msg = _extract_error_message(str(e))
                err_info = _categorize_error(str(e))

                lines = [f"[red]{msg}[/red]"]
                if err_info.get("hint"):
                    lines.append(f"\n[yellow]\U0001f4a1 {err_info['hint']}[/yellow]")
                if err_info.get("diagnostic"):
                    lines.append(f"\n[dim]\u2192 Run [bold]{err_info['diagnostic']}[/bold] for diagnostics[/dim]")
                lines.append(f"\n[dim]Type /retry to retry your last message[/dim]")

                con.print(Panel(
                    "\n".join(lines),
                    title=f"[bold red]{err_info['category'].replace('_', ' ').title()} Error[/bold red]",
                    border_style="red"
                ))

                if err_info.get("auto_health"):
                    try:
                        from backend.core.health import get_registry
                        registry = get_registry()
                        results = await registry.check_all()
                        con.print()
                        con.print("[bold yellow]\u2500\u2500 Health check results \u2500\u2500[/bold yellow]")
                        for name, s in sorted(results.items()):
                            st = s.get("status", "?")
                            color = {"ok": "green", "degraded": "yellow", "down": "red",
                                     "not_configured": "dim", "unknown": "dim"}.get(st, "dim")
                            con.print(f"  [{color}]{'\u2713' if st == 'ok' else '\u26a0' if st == 'degraded' else '\u2717'} {name:15s} {st}[/{color}]")
                        con.print()
                    except Exception:
                        pass

                await _refresh_banner(con, memory, settings)

    finally:
        # Clean exit — clear crash state
        _clear_crash_state()
        _save_history()
        await shutdown_application()


# ═══════════════════════════════════════════════════════════════════════
# Textual TUI mode
# ═══════════════════════════════════════════════════════════════════════

async def run_tui():
    """Run the agent with the full-screen Textual TUI.

    The TUI launches immediately with a loading state, then initializes
    the backend in the background so the user isn't staring at a blank
    terminal for 20+ seconds while ML models load.
    """
    _suppress_logs()

    from cli.tui import AmalgamTUI

    # Launch the TUI immediately with no backend (shows loading state)
    app = AmalgamTUI()

    # Background init task — we cancel it if the user exits early
    init_task: asyncio.Task | None = None

    async def _init_backend():
        """Initialize the backend and wire it to the running TUI."""
        try:
            from backend.core.startup import init_application, shutdown_application
            await init_application()
            _suppress_logs()

            from backend.core.deps import get_shared
            shared = get_shared()
            agent = shared["agent"]
            memory = shared["memory"]
            settings = shared["settings"]
            llm = shared["llm"]

            if _CLI_ARGS:
                _apply_cli_settings(settings, llm, memory, _CLI_ARGS)

            # Mark this session as TUI mode so backend uses appropriate STT engine
            try:
                settings.set("ui.mode", "tui")
            except Exception:
                pass

            _check_crash_recovery_in_tui(settings, memory)

            sid = memory.get_current_session() if memory else ""
            active = settings.get("provider.active", "") if settings else ""
            model = settings.get(f"provider.{active}.model", "") if active and settings else ""
            _save_snapshot(sid, active, model)

            # Wire up the backend to the running app
            app.set_backend(settings, llm, memory, agent)

        except asyncio.CancelledError:
            log.info("Backend init cancelled (user exited TUI)")
            raise
        except Exception as e:
            log.error("Backend init failed: %s", e)
            try:
                app.show_error(f"Backend initialization failed: {e}")
            except Exception:
                pass

    async def _run():
        nonlocal init_task
        init_task = asyncio.create_task(_init_backend())
        try:
            await app.run_async()
        finally:
            # If the app exits before init completes, cancel the init task
            if init_task and not init_task.done():
                init_task.cancel()
                try:
                    await init_task
                except asyncio.CancelledError:
                    pass

    try:
        await _run()
    finally:
        _clear_crash_state()
        _save_history()
        try:
            from backend.core.startup import shutdown_application
            await shutdown_application()
        except Exception:
            pass


def _check_crash_recovery_in_tui(settings, memory):
    """Check for crash state from previous session and recover if needed.

    In the TUI context we can't show a Confirm prompt (no console available
    before the app starts), so we just log and auto-recover.
    """
    crash_file = os.path.join(os.path.expanduser("~"), ".amalgam", "crash_state.json")
    if not os.path.exists(crash_file):
        return

    try:
        with open(crash_file) as f:
            crash = json.load(f)
        os.remove(crash_file)

        crash_sid = crash.get("session_id", "")
        crash_msg = crash.get("last_message", "")

        if crash_sid and memory:
            try:
                memory.set_current_session(crash_sid)
                log.info("Auto-recovered crashed session: %s", crash_sid[:20])
            except Exception:
                pass
    except Exception:
        try:
            os.remove(crash_file)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# gRPC mode
# ═══════════════════════════════════════════════════════════════════════

async def run_cli_grpc(host: str = "localhost", port: int = 50051):
    """Connect to a remote gRPC agent server."""
    import grpc
    from backend.grpc import agent_pb2, agent_pb2_grpc
    from rich.panel import Panel

    con = _make_console()
    _show_thinking = [True]

    async with grpc.aio.insecure_channel(f"{host}:{port}") as channel:
        stub = agent_pb2_grpc.AgentServiceStub(channel)
        con.print(f"[green]Connected to gRPC server at[/green] {host}:{port}")
        con.print("[dim]Type /exit to quit[/dim]\n")

        while True:
            try:
                text = con.input("[bold cyan]>[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                con.print()
                break

            if not text:
                continue
            if text == "/exit":
                break

            async def send():
                yield agent_pb2.ChatRequest(text=text)

            from rich.prompt import Prompt
            try:
                async for response in stub.Chat(send()):
                    which = response.WhichOneof("payload")
                    if which == "text_chunk":
                        con.print(response.text_chunk, end="")
                    elif which == "thinking":
                        if _show_thinking[0]:
                            con.print(f"[dim]\\[thinking] {response.thinking}[/dim]")
                    elif which == "tool_call":
                        tc = response.tool_call
                        con.print(Panel(
                            f"[cyan]{tc.name}({tc.args_json})[/cyan]",
                            title="Tool", border_style="cyan"
                        ))
                    elif which == "permission_request":
                        pr = response.permission_request
                        con.print(Panel(
                            f"[yellow]{pr.cmd}[/yellow]",
                            title="Permission Needed", border_style="yellow"
                        ))
                        Prompt.ask("  Options", choices=list(pr.options), default="deny")
                    elif which == "error":
                        con.print(Panel(
                            f"[red]{response.error}[/red]",
                            title="Error", border_style="red"
                        ))
                    elif which == "done":
                        con.print()
                        break
            except Exception as e:
                msg = _extract_error_message(str(e))
                con.print(Panel(
                    f"[red]{msg}[/red]",
                    title="[bold red]Connection Error[/bold red]",
                    border_style="red"
                ))


# ═══════════════════════════════════════════════════════════════════════
# Subcommand handlers
# ═══════════════════════════════════════════════════════════════════════

def _handle_serve(args):
    """Handle 'python main.py cli serve'."""
    host = args.grpc_host or daemon.DEFAULT_HOST
    port = args.grpc_port or daemon.DEFAULT_PORT

    if args.daemon:
        # Called by daemon manager: write PID and run in foreground
        daemon._write_pid(os.getpid())
        with open(daemon.STATUS_FILE, "w") as f:
            json.dump({"host": host, "port": port, "started_at": time.time()}, f)

        from backend.core.log_config import configure_logging
        configure_logging(level=args.log_level or "ERROR")

        from backend.grpc.server import serve_grpc
        try:
            asyncio.run(serve_grpc(host, port))
        except Exception:
            pass
        finally:
            daemon._clear_pid()
            os._exit(0)
    else:
        # User explicitly called 'serve' — start as daemon
        import cli.server as daemon_mod
        result = daemon_mod.start(host, port, args.log_level or "ERROR", daemonize=True)
        if result.get("running"):
            human_markup(f"[green]\u2713[/green] gRPC daemon started on {host}:{port} [dim](PID {result['pid']})[/dim]")
        else:
            human_markup(f"[red]\u2717[/red] Failed to start daemon")
            sys.exit(1)


def _handle_stop(args):
    """Handle 'python main.py cli stop'."""
    result = daemon.stop()
    if not result.get("running"):
        human_markup("[green]\u2713[/green] Daemon stopped")
    else:
        human_markup("[red]\u2717[/red] Failed to stop daemon")
        sys.exit(1)


def _handle_status(args):
    """Handle 'python main.py cli status' — standalone, no backend needed."""
    st = daemon.status()
    rows = [
        ("Daemon", "[green]Running[/green]" if st["running"] else "[red]Stopped[/red]"),
        ("PID", str(st["pid"]) if st["pid"] else "[dim]\u2014[/dim]"),
        ("Host", st.get("host", daemon.DEFAULT_HOST)),
        ("Port", str(st.get("port", daemon.DEFAULT_PORT))),
    ]
    if st.get("uptime"):
        uptime_str = f"{st['uptime']:.0f}s"
        if st["uptime"] > 120:
            uptime_str = f"{st['uptime']/60:.1f}m"
        rows.append(("Uptime", uptime_str))

    # Detect providers from env vars (no backend needed)
    providers = _detect_providers_from_env()
    if providers:
        prov_str = ", ".join(f"[green]{p}[/green]" for p in providers)
        rows.append(("Providers", prov_str))
    else:
        rows.append(("Providers", "[yellow]None configured[/yellow]"))

    rows.append(("Version", f"[cyan]{VERSION}[/cyan]"))

    if wants_json():
        print(json.dumps({"type": "status", "daemon": st, "version": VERSION}))
    else:
        from cli.output import human_table
        human_table(rows, caption="Amalgam Status")


def _detect_providers_from_env() -> list[str]:
    """Detect which provider API keys are set in the environment."""
    import os
    env_keys = {
        "anthropic": ["ANTHROPIC_API_KEY"],
        "anthropic-compat": ["ANTHROPIC_COMPAT_API_KEY"],
        "deepseek": ["DEEPSEEK_API_KEY"],
        "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "groq": ["GROQ_API_KEY"],
        "huggingface": ["HUGGINGFACE_API_KEY"],
        "mistral": ["MISTRAL_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "openai-compat": ["OPENAI_COMPAT_API_KEY"],
        "openrouter": ["OPENROUTER_API_KEY"],
        "siliconflow": ["SILICONFLOW_API_KEY"],
        "together": ["TOGETHER_API_KEY"],
        "zai": ["ZAI_API_KEY"],
    }
    result = []
    for name, keys in env_keys.items():
        for k in keys:
            if k in os.environ and os.environ[k].strip():
                result.append(name)
                break
    return result


def _handle_login(args):
    """Handle 'python main.py cli login <provider>'."""
    if not args.login_provider:
        human_markup("[red]Usage:[/red] python main.py cli login <provider>")
        human_markup(f"[dim]Providers: {', '.join(KNOWN_PROVIDERS)}[/dim]")
        # Show login table using env-only detection (no backend)
        settings = _load_settings_standalone()
        if settings:
            auth_mod.show_login_table(settings)
        sys.exit(1)

    settings = _load_settings_standalone()
    if not settings:
        human_markup("[red]Failed to load settings.[/red]")
        sys.exit(1)
    success = auth_mod.login_provider(settings, args.login_provider)
    sys.exit(0 if success else 1)


def _handle_login_status(args):
    """Handle 'python main.py cli login-status' — standalone, no backend needed."""
    settings = _load_settings_standalone()
    if wants_json():
        if settings:
            prov = auth_mod.login_status(settings)
        else:
            prov = []
        print(json.dumps({"type": "login_status", "providers": prov}))
    else:
        if settings:
            auth_mod.show_login_table(settings)
        else:
            human_markup("[yellow]No settings file found.[/yellow]")
            env_providers = _detect_providers_from_env()
            if env_providers:
                human_markup(f"[dim]Found keys in env: {', '.join(env_providers)}[/dim]")


def _load_settings_standalone():
    """Load settings directly without full backend initialization."""
    try:
        from backend.core.config.settings import Settings
        from backend.core.paths import SETTINGS_PATH
        return Settings(path=str(SETTINGS_PATH))
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# Run (one-shot)
# ═══════════════════════════════════════════════════════════════════════

async def _run_once(provider: str | None, model: str | None,
                     resume: str | None, message: str,
                     json_output: bool, ndjson_output: bool) -> int:
    """Send a single message and stream the response. Returns exit code."""
    from backend.core.startup import init_application, shutdown_application
    _suppress_logs()
    await init_application()
    _suppress_logs()
    from backend.core.deps import get_shared

    shared = get_shared()
    agent = shared["agent"]
    memory = shared["memory"]
    settings = shared["settings"]
    llm = shared["llm"]

    exit_code = 0

    try:
        # Apply --provider / --model
        if provider:
            settings.set("provider.active", provider)
            llm.reload_settings()
        if model:
            prov = settings.get("provider.active", "?")
            settings.set(f"provider.{prov}.model", model)
            llm.reload_settings()

        # Mark as TUI mode for one-shot runs too
        try:
            settings.set("ui.mode", "tui")
        except Exception:
            pass

        # Apply --resume
        if resume:
            try:
                memory.set_current_session(resume)
            except Exception:
                human_status(f"[yellow]Session '{resume}' not found, starting fresh[/yellow]")

        # Print banner in human mode
        if not json_output and not ndjson_output:
            sid = memory.get_current_session()
            active = settings.get("provider.active", "?")
            model_val = settings.get(f"provider.{active}.model", "?")
            out_markup(f"[bold yellow]=== One-shot ({active}/{model_val}) ===[/bold yellow]")

        # Collect full response
        full_text = ""
        async for chunk in agent.handle_user_input(message):
            if isinstance(chunk, tuple):
                tag_type, tag_val = chunk
                if tag_type == "__thinking__":
                    if ndjson_output:
                        print(json.dumps({"type": "thinking", "content": tag_val}))
                    # Skip thinking in json and human single-shot modes
                elif tag_type == "__error__":
                    if ndjson_output:
                        print(json.dumps({"type": "error", "content": tag_val}))
                    else:
                        human_status(f"[red]Error: {tag_val}[/red]")
                    exit_code = 1
                elif tag_type == "__tool__":
                    if ndjson_output:
                        print(json.dumps({"type": "tool", "content": tag_val}))
                    elif not json_output:
                        human_status(f"[dim]Tool: {tag_val}[/dim]")
                elif tag_type == "__roleplay__":
                    if ndjson_output:
                        print(json.dumps({"type": "roleplay", "content": tag_val}))
                    elif not json_output:
                        print(f"\n[yellow]* {tag_val} *[/yellow]")
                elif tag_type == "__permission__":
                    if not json_output and not ndjson_output:
                        human_status(f"[yellow]Permission needed: {tag_val}[/yellow]")
                else:
                    full_text += str(tag_val)
            else:
                full_text += str(chunk)
                if not json_output and not ndjson_output:
                    print(chunk, end="", flush=True)

        if not json_output and not ndjson_output:
            print()  # final newline

        # Emit final JSON result
        if json_output:
            print(json.dumps({
                "type": "result",
                "content": full_text.strip(),
                "session_id": memory.get_current_session(),
                "provider": settings.get("provider.active", "?"),
                "model": settings.get(f"{settings.get('provider.active', '?')}.model", "?"),
            }))
    except Exception as e:
        msg = _extract_error_message(str(e))
        if json_output:
            print(json.dumps({"type": "error", "content": msg}))
        elif ndjson_output:
            print(json.dumps({"type": "error", "content": msg}))
        else:
            human_status(f"[red]Error: {msg}[/red]")
        exit_code = 1
    finally:
        await shutdown_application()

    return exit_code


def _handle_run(args):
    """Handle 'python main.py cli run <message>' — one-shot send-and-exit."""
    # Capture remaining args after 'run' as the message
    import sys
    run_args = [a for a in sys.argv[sys.argv.index('run') + 1:]
                if not a.startswith('-')]
    if not run_args:
        human_markup("[red]Usage:[/red] python main.py cli run <message>")
        human_markup("[dim]Example: python main.py cli run \"Hello, who are you?\"[/dim]")
        sys.exit(1)
    message = " ".join(run_args)

    exit_code = asyncio.run(_run_once(
        provider=args.provider,
        model=args.model,
        resume=args.resume,
        message=message,
        json_output=args.json,
        ndjson_output=args.ndjson,
    ))
    sys.exit(exit_code)


# ═══════════════════════════════════════════════════════════════════════
# Auth (consolidated status)
# ═══════════════════════════════════════════════════════════════════════

def _handle_auth(args):
    """Handle 'python main.py cli auth' — consolidated auth status."""
    settings = _load_settings_standalone()
    env_providers = _detect_providers_from_env()

    if wants_json():
        if settings:
            prov = auth_mod.login_status(settings)
        else:
            prov = [{"name": p, "has_key": True, "source": "env"}
                    for p in env_providers]
        print(json.dumps({"type": "auth", "providers": prov}))
    else:
        from rich.table import Table
        from rich import box
        from rich.console import Console
        con = Console()

        con.print()
        con.print("[bold]=== Authentication Status ===[/bold]")

        # Section 1: From settings
        if settings:
            prov_data = auth_mod.login_status(settings)
            tbl = Table(box=box.SIMPLE, show_header=True)
            tbl.add_column("Provider", style="cyan")
            tbl.add_column("Key", justify="center")
            tbl.add_column("Source", style="dim")
            tbl.add_column("Model", style="green")
            for p in prov_data:
                key_status = "[green]\u2713[/green]" if p["has_key"] else "[red]\u2717[/red]"
                src = {"config": "settings", "env": "env var", "default": ""}.get(p["source"], p["source"])
                tbl.add_row(p["display_name"], key_status, src, p["model"] or "\u2014")
            con.print(tbl)
        else:
            con.print("[yellow]  No settings file found.[/yellow]")

        # Section 2: Additional env-only providers (not in settings)
        if env_providers:
            env_only = [p for p in env_providers
                        if not settings or not any(s["name"] == p and s["has_key"]
                                                    for s in auth_mod.login_status(settings))]
            if env_only:
                con.print(f"\n[dim]Env-only keys: {', '.join(env_only)}[/dim]")

        # Section 3: Help
        con.print()
        con.print("[dim]To add a key: python main.py cli login <provider>[/dim]")
        con.print("[dim]Example:      python main.py cli login gemini[/dim]")


def _apply_cli_settings(settings, llm, memory, args) -> None:
    """Apply --provider, --model, --resume from CLI args after init.

    Called after init_application(), before entering the main loop.
    """
    changed = False

    if args.provider:
        settings.set("provider.active", args.provider)
        changed = True

    if args.model:
        prov = args.provider or settings.get("provider.active", "?")
        settings.set(f"provider.{prov}.model", args.model)
        changed = True

    if changed:
        llm.reload_settings()

    if args.resume:
        memory.set_current_session(args.resume)
    elif args.resume is not None:
        # --resume with no argument: list sessions
        try:
            sessions = memory.get_sessions()
            if sessions:
                human_markup(f"[cyan]Available sessions:[/cyan]")
                for s in sessions:
                    sid = s.get("id", "?")
                    title = s.get("title") or ""
                    human_markup(f"  [dim]{sid[:20]}[/dim]  {title}")
            else:
                human_markup("[yellow]No saved sessions.[/yellow]")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Full-functioning CLI mode")
    parser.add_argument(
        "action",
        nargs="?",
        default=None,
        choices=["auth", "cli", "login", "login-status", "run", "serve", "status", "stop"],
        help="Subcommand: serve|stop|status|login|login-status|auth|run|cli",
    )
    parser.add_argument("login_provider", nargs="?", default=None,
                        help="Provider name for login subcommand")
    parser.add_argument("--grpc", action="store_true", help="Connect via gRPC")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode (internal)")
    parser.add_argument("--host", default=daemon.DEFAULT_HOST, help="gRPC host")
    parser.add_argument("--grpc-host", default=daemon.DEFAULT_HOST, help="gRPC bind/connect host")
    parser.add_argument("--port", type=int, default=daemon.DEFAULT_PORT, help="gRPC port (legacy)")
    parser.add_argument("--grpc-port", type=int, default=daemon.DEFAULT_PORT, help="gRPC bind/connect port")
    parser.add_argument("--check", action="store_true", help="Run pre-flight diagnostics")
    parser.add_argument("--verbose", action="store_true", help="Detailed diagnostic output")
    parser.add_argument("--version", action="store_true", help="Show version")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--ndjson", action="store_true", help="Newline-delimited JSON output")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error output")
    parser.add_argument("--log-level", default=None,
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Override log level")
    parser.add_argument("--log-format", default=None, choices=["console", "json"],
                        help="Log output format")
    parser.add_argument("--provider", default=None,
                        help="Provider to use (e.g. gemini, openai, anthropic)")
    parser.add_argument("--model", default=None,
                        help="Model to use (e.g. gpt-4o, gemini-2.5-flash)")
    parser.add_argument("--resume", default=None, nargs="?",
                        help="Resume a session by ID, or list sessions if no ID provided")
    args, extra = parser.parse_known_args()

    # When invoked as `python main.py cli status`, the first positional
    # arg `cli` is consumed by `action`, and `status` ends up in `extra`.
    # Re-parse: if action is 'cli' or None, look for a subcommand in extra.
    if args.action in (None, "cli") and extra:
        # Parse extra as the new argv (no program name needed for subcommands)
        args, extra = parser.parse_known_args(extra)

    # ── Set output format ─────────────────────────────────────────────
    if args.json:
        set_output_format("json")
    elif args.ndjson:
        set_output_format("ndjson")

    if args.quiet:
        sys.stderr = open(os.devnull, 'w')

    if args.version:
        if wants_json():
            print(json.dumps({"type": "version", "version": VERSION}))
        else:
            from rich.console import Console
            Console().print(f"[bold yellow]Amalgam[/bold yellow] version [cyan]{VERSION}[/cyan]")
        sys.exit(0)

    # ── Subcommand dispatch ───────────────────────────────────────────
    if args.action == "serve":
        _handle_serve(args)
        return
    elif args.action == "stop":
        _handle_stop(args)
        return
    elif args.action == "status":
        _handle_status(args)
        return
    elif args.action == "login":
        _handle_login(args)
        return
    elif args.action == "login-status":
        _handle_login_status(args)
        return
    elif args.action == "auth":
        _handle_auth(args)
        return
    elif args.action == "run":
        _handle_run(args)
        return
    elif args.action == "cli":
        pass  # Fall through to normal CLI mode (invoked via main.py cli ...)

    # ── Diagnostics ───────────────────────────────────────────────────
    if args.check:
        _suppress_logs()
        from backend.core.startup import init_application, shutdown_application
        from rich.console import Console
        con = Console()

        async def run_diag():
            await init_application()
            _suppress_logs()
            ok = await _run_check(verbose=args.verbose)
            await shutdown_application()
            sys.exit(0 if ok else 1)

        asyncio.run(run_diag())
        return

    # ── Normal CLI mode ───────────────────────────────────────────────
    from backend.core.log_config import configure_logging
    logger = configure_logging(level=args.log_level, log_format=args.log_format)

    global _CLI_ARGS
    _CLI_ARGS = args

    try:
        if args.grpc:
            host = args.grpc_host or args.host
            port = args.grpc_port or args.port
            asyncio.run(run_cli_grpc(host, port))
        elif args.json or args.ndjson:
            # Machine-readable output uses the old REPL
            asyncio.run(run_cli_direct())
        elif wants_human():
            if sys.stdout.isatty():
                # Full-screen Textual TUI (default)
                asyncio.run(run_tui())
            else:
                # Non-TTY: fall back to old REPL
                asyncio.run(run_cli_direct())
        else:
            asyncio.run(run_cli_direct())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
