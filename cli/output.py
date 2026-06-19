"""
Output formatters for the Amalgam CLI.

Supports human-readable (Rich), JSON, and NDJSON output modes.
Set via CLI flags: --json, --ndjson, or per-command context.
"""
import json
import sys
from enum import Enum
from typing import Any


class OutputFormat(str, Enum):
    HUMAN = "human"
    JSON = "json"
    NDJSON = "ndjson"


_FORMAT = OutputFormat.HUMAN


def set_output_format(fmt: str | OutputFormat) -> None:
    """Set the global output format."""
    global _FORMAT
    if isinstance(fmt, str):
        fmt = OutputFormat(fmt.lower())
    _FORMAT = fmt


def get_output_format() -> OutputFormat:
    """Get the current output format."""
    return _FORMAT


def wants_human() -> bool:
    return _FORMAT == OutputFormat.HUMAN


def wants_json() -> bool:
    return _FORMAT == OutputFormat.JSON


# ---------------------------------------------------------------------------
# Human output  (Rich console)
# ---------------------------------------------------------------------------

def _console():
    from rich.console import Console
    return Console()


def _stderr_console():
    from rich.console import Console
    return Console(stderr=True)


def human_banner(session_id: str, provider: str, model: str,
                 title: str | None = None, health: dict | None = None) -> None:
    """Print the startup banner using Rich panels. (stderr — status/diagnostic)"""
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    con = _stderr_console()

    grid = Table.grid(padding=1)
    grid.add_column(style="cyan")
    grid.add_column()
    grid.add_row("Session", f"[bold]{title or session_id[:16]}[/bold]")
    grid.add_row("Provider", provider)
    grid.add_row("Model", model)

    if health:
        dots = []
        for name, status in sorted(health.items()):
            color = {"ok": "green", "degraded": "yellow", "down": "red",
                     "not_configured": "dim", "unknown": "dim"}.get(status, "dim")
            dots.append(f"[{color}]{name}:{status}[/{color}]")
        grid.add_row("Services", "  ".join(dots))

    con.print(Panel(grid, title="[bold yellow]Amalgam[/bold yellow]", border_style="yellow"))
    con.print("[dim]Type /exit to quit, /new for new session, /help for commands[/dim]\n")


def human_msg(text: str, end: str = "") -> None:
    """Print a message chunk."""
    _console().print(text, end=end)


def human_error(msg: str, title: str = "Error", hint: str | None = None,
                diagnostic: str | None = None) -> None:
    """Print a formatted error panel. (stderr — diagnostic)"""
    from rich.panel import Panel
    lines = [f"[red]{msg}[/red]"]
    if hint:
        lines.append(f"\n[yellow]\U0001f4a1 {hint}[/yellow]")
    if diagnostic:
        lines.append(f"\n[dim]\u2192 Run [bold]{diagnostic}[/bold] for diagnostics[/dim]")
    _stderr_console().print(Panel(
        "\n".join(lines),
        title=f"[bold red]{title}[/bold red]",
        border_style="red"
    ))


def human_table(rows: list[tuple], headers: list[str] | None = None,
                caption: str | None = None) -> None:
    """Print a Rich table with rows and optional headers."""
    from rich.table import Table
    from rich import box
    tbl = Table(box=box.SIMPLE, show_header=bool(headers))
    if headers:
        for h in headers:
            tbl.add_column(h)
    else:
        tbl.add_column("Key", style="cyan")
        tbl.add_column("Value")
    for row in rows:
        tbl.add_row(*[str(c) for c in row])
    if caption:
        tbl.caption = caption
    _console().print(tbl)


def human_panel(content: str, title: str = "", border_style: str = "cyan") -> None:
    """Print a Rich panel."""
    from rich.panel import Panel
    _console().print(Panel(content, title=title, border_style=border_style))


def human_markup(text: str) -> None:
    """Print Rich-markup text. (stderr — status/diagnostic)"""
    _stderr_console().print(text)


def human_status(text: str) -> None:
    """Print a status line to stderr (not captured by --json)."""
    _stderr_console().print(text)


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def _json_out(obj: dict) -> None:
    """Write a JSON object to stdout."""
    json.dump(obj, sys.stdout, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _ndjson_out(obj: dict) -> None:
    """Write a newline-delimited JSON object."""
    json.dump(obj, sys.stdout, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()


def json_banner(session_id: str, provider: str, model: str,
                title: str | None = None, health: dict | None = None) -> None:
    """Emit a banner as JSON."""
    obj: dict[str, Any] = {
        "type": "banner",
        "session_id": session_id,
        "provider": provider,
        "model": model,
        "title": title or session_id[:16],
    }
    if health:
        obj["health"] = health
    _json_out(obj)


def json_msg(text: str, end: str = "") -> None:
    """Emit a message chunk as JSON. end parameter is ignored in JSON mode."""
    _ndjson_out({"type": "message", "content": text})


def json_error(msg: str, title: str = "Error", hint: str | None = None,
               diagnostic: str | None = None) -> None:
    """Emit an error as JSON."""
    obj: dict[str, Any] = {"type": "error", "message": msg, "title": title}
    if hint:
        obj["hint"] = hint
    if diagnostic:
        obj["diagnostic"] = diagnostic
    _json_out(obj)


def json_table(rows: list[tuple], headers: list[str] | None = None,
               caption: str | None = None) -> None:
    """Emit tabular data as JSON."""
    _json_out({
        "type": "table",
        "headers": headers or [],
        "rows": [[str(c) for c in row] for row in rows],
        "caption": caption or "",
    })


def json_panel(content: str, title: str = "", border_style: str = "cyan") -> None:
    """Emit a panel as JSON."""
    _json_out({"type": "panel", "content": content, "title": title})


def json_markup(text: str) -> None:
    """Emit a markup line as JSON."""
    _ndjson_out({"type": "markup", "content": text})


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def banner(session_id: str, provider: str, model: str,
           title: str | None = None, health: dict | None = None) -> None:
    """Output a banner in the current format."""
    if wants_human():
        human_banner(session_id, provider, model, title, health)
    else:
        json_banner(session_id, provider, model, title, health)


def message(text: str, end: str = "") -> None:
    """Output a message chunk in the current format."""
    if wants_human():
        human_msg(text, end)
    else:
        json_msg(text, end)


def error(msg: str, title: str = "Error", hint: str | None = None,
          diagnostic: str | None = None) -> None:
    """Output an error in the current format."""
    if wants_human():
        human_error(msg, title, hint, diagnostic)
    else:
        json_error(msg, title, hint, diagnostic)


def table(rows: list[tuple], headers: list[str] | None = None,
          caption: str | None = None) -> None:
    """Output a table in the current format."""
    if wants_human():
        human_table(rows, headers, caption)
    else:
        json_table(rows, headers, caption)


def panel(content: str, title: str = "", border_style: str = "cyan") -> None:
    """Output a panel in the current format."""
    if wants_human():
        human_panel(content, title, border_style)
    else:
        json_panel(content, title, border_style)


def markup(text: str) -> None:
    """Output Rich markup / JSON markup."""
    if wants_human():
        human_markup(text)
    else:
        json_markup(text)
