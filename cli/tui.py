"""
Amalgam TUI — full-screen chat interface inspired by jcode's TUI design.

Inline dropdown for commands/providers/models (jcode-style), not a modal popup.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import signal
from typing import Any, AsyncIterator

from rich.align import Align
from rich.markdown import Markdown
from rich.panel import Panel
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, RichLog, Label, Static
from textual import work as textual_work

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# Color palette — Tokyo Night
# ═══════════════════════════════════════════════════════════════════════

_BG        = "#1a1b26"
_SURFACE   = "#24253a"
_SURFACE2  = "#2a2b41"
_BORDER    = "#3b3d5c"
_TEXT      = "#c0caf5"
_DIM       = "#565f89"
_MUTED     = "#444b6a"
_ACCENT    = "#7aa2f7"
_GREEN     = "#9ece6a"
_RED       = "#f7768e"
_YELLOW    = "#e0af68"
_CYAN      = "#7dcfff"
_MAGENTA   = "#bb9af7"
_ORANGE    = "#ff9e64"
_PINK      = "#ff96c8"

# ═══════════════════════════════════════════════════════════════════════
# Theme palettes
# ═══════════════════════════════════════════════════════════════════════

_THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#1a1b26", "surface": "#24253a", "surface2": "#2a2b41",
        "border": "#3b3d5c", "text": "#c0caf5", "dim": "#565f89",
        "muted": "#444b6a", "accent": "#7aa2f7", "green": "#9ece6a",
        "red": "#f7768e", "yellow": "#e0af68", "cyan": "#7dcfff",
        "magenta": "#bb9af7", "orange": "#ff9e64", "pink": "#ff96c8",
    },
    "midnight": {
        "bg": "#0f0f1a", "surface": "#1a1a2e", "surface2": "#22223a",
        "border": "#2a2a4a", "text": "#e0e0ff", "dim": "#6666aa",
        "muted": "#555588", "accent": "#6c9fff", "green": "#7ecc8f",
        "red": "#ff6b8a", "yellow": "#f0c674", "cyan": "#7dd4cf",
        "magenta": "#c59bff", "orange": "#ffa870", "pink": "#ff90b8",
    },
    "light": {
        "bg": "#fafafa", "surface": "#f0f0f0", "surface2": "#e8e8e8",
        "border": "#cccccc", "text": "#1a1a2e", "dim": "#888888",
        "muted": "#aaaaaa", "accent": "#3366cc", "green": "#2e8b57",
        "red": "#cc3344", "yellow": "#b8860b", "cyan": "#008b8b",
        "magenta": "#8844aa", "orange": "#cc6600", "pink": "#cc4488",
    },
    "nord": {
        "bg": "#2e3440", "surface": "#3b4252", "surface2": "#434c5e",
        "border": "#4c566a", "text": "#eceff4", "dim": "#616e88",
        "muted": "#7b88a1", "accent": "#88c0d0", "green": "#a3be8c",
        "red": "#bf616a", "yellow": "#ebcb8b", "cyan": "#8fbcbb",
        "magenta": "#b48ead", "orange": "#d08770", "pink": "#d08770",
    },
}


def _apply_palette(name: str) -> None:
    """Apply a named color palette to the module-level color globals."""
    global _BG, _SURFACE, _SURFACE2, _BORDER, _TEXT, _DIM, _MUTED
    global _ACCENT, _GREEN, _RED, _YELLOW, _CYAN, _MAGENTA, _ORANGE, _PINK
    p = _THEMES.get(name, _THEMES["dark"])
    _BG = p["bg"]
    _SURFACE = p["surface"]
    _SURFACE2 = p["surface2"]
    _BORDER = p["border"]
    _TEXT = p["text"]
    _DIM = p["dim"]
    _MUTED = p["muted"]
    _ACCENT = p["accent"]
    _GREEN = p["green"]
    _RED = p["red"]
    _YELLOW = p["yellow"]
    _CYAN = p["cyan"]
    _MAGENTA = p["magenta"]
    _ORANGE = p["orange"]
    _PINK = p["pink"]

# ═══════════════════════════════════════════════════════════════════════
# Dynamic command registry
# ═══════════════════════════════════════════════════════════════════════

_COMMAND_DEFS: dict[str, tuple[str, str, list[str] | None]] = {}
"""Maps command -> (description, help_text, arg_completer_type|None)"""


def _init_command_registry():
    """Build the command registry from all available sources."""
    if _COMMAND_DEFS:
        return

    core: list[tuple[str, str, str, list[str] | None]] = [
        ("exit",     "Quit the application",               "Exit Amalgam", None),
        ("quit",     "Quit the application",               "Exit Amalgam", None),
        ("clear",    "Clear the chat display",             "Clear all messages from view", None),
        ("new",      "Start a new session",                "Clear chat and start a fresh session", None),
        ("help",     "Show this help",                     "Display command reference", None),
        ("think",    "Toggle/on/off thinking display",    "Show or hide thinking traces", None),
        ("provider", "Manage providers (add|set|rm)", "Add, update, or remove a provider's API key", ["provider"]),
        ("model",    "Switch model",                       "Change the active model for the current provider", ["model"]),
        ("rename",   "Rename the current session",         "Give the session a new title", None),
        ("resume",   "Show last 5 turns of current session","Display recent conversation history", None),
        ("compact",  "Force memory compaction",            "Compress session context", None),
        ("health",   "Show service health",                "Display system health status", None),
        ("companion","Toggle/on/off companion mode",      "Enable or disable companion personality", None),
        ("settings", "Show/set a setting",                 "View or change a configuration key", None),
        ("memory",   "Show memory usage",                  "Display memory stats (sessions, messages)", None),
        ("stats",    "Show analytics",                     "Tool-usage and cost analytics", None),
        ("theme",    "Switch UI theme",                    "Change color theme (dark, midnight, light, nord)", None),
        ("character","Load a character",                   "Switch active character/persona", None),
        ("profile",  "Switch settings profile",            "Change profile (token-friendly, default, quality, custom)", None),
        ("permission","Set permission level",              "Set permission level (readonly|confirm|full)", None),
    ]

    for name, desc, help_text, arg_type in core:
        _COMMAND_DEFS[name] = (desc, help_text, arg_type)
        _COMMAND_DEFS["/" + name] = (desc, help_text, arg_type)


def get_commands() -> dict[str, tuple[str, str, list[str] | None]]:
    _init_command_registry()
    return dict(_COMMAND_DEFS)


def get_slash_commands() -> list[str]:
    return sorted([k for k in get_commands().keys() if k.startswith("/")])


def get_detected_providers(settings: Any) -> list[str]:
    """Get list of configured provider names that have API keys configured."""
    _all_known = ["gemini", "openai", "anthropic", "groq", "ollama", "openrouter",
                  "deepseek", "siliconflow", "zai", "mistral", "together",
                  "huggingface", "llamacpp", "koboldai", "aws", "gcp",
                  "opencode", "opendev"]

    try:
        from cli.provider import detect_providers
        providers = detect_providers(settings)
        detected = [p.name for p in providers if p.has_api_key]
        if detected:
            return sorted(detected)
    except Exception as e:
        log.debug("detect_providers() failed: %s", e)

    # Fallback: check provider configs directly for api_key
    try:
        active = []
        for name in _all_known:
            try:
                cfg = settings.get(f"provider.{name}")
                if cfg and isinstance(cfg, dict) and cfg.get("api_key"):
                    active.append(name)
            except Exception as e:
                log.debug("Failed to check provider %s config: %s", name, e)
        if active:
            return active
    except Exception as e:
        log.debug("Fallback provider detection failed: %s", e)

    # No authenticated providers found
    return []


def get_models_for_provider(settings: Any, provider: str) -> list[str]:
    """Get known models for a provider from the canonical model list.

    Proxy providers (opencode, opendev) that route through an MCP gateway
    can use *any* model, so this returns the union of all known models
    instead of an empty list.
    """
    if not provider or not isinstance(provider, str):
        return []

    p = provider.strip().lower()
    if not p:
        return []

    try:
        from cli.provider import PROVIDER_MODELS
    except ImportError:
        return []

    # Proxy providers can route to any upstream model → return everything
    if p in ("opencode", "opendev"):
        all_models: list[str] = []
        for mlist in PROVIDER_MODELS.values():
            all_models.extend(mlist)
        return all_models

    if p in PROVIDER_MODELS:
        return list(PROVIDER_MODELS[p])

    return []


def fuzzy_filter(query: str, items: list[str]) -> list[str]:
    """Simple prefix + substring fuzzy filter.

    Strips leading / from items when matching so e.g. /health matches 'h'.
    """
    q = query.lower()
    if not q:
        return list(items)

    # Strip leading / for matching purposes
    def match_key(item: str) -> str:
        k = item.lower()
        return k.lstrip("/")

    prefix = [i for i in items if match_key(i).startswith(q)]
    substr = [i for i in items if i not in prefix and q in match_key(i)]
    return prefix + substr


# ═══════════════════════════════════════════════════════════════════════
# Inline Dropdown (jcode-style, above the input)
# ═══════════════════════════════════════════════════════════════════════

class InlineDropdown(Widget):
    """Inline dropdown list that appears above the input area.

    Shows a filtered list of items (commands, providers, or models).
    Controlled by the parent AmalgamTUI.
    """

    items = reactive[list[tuple[str, str]]]([])
    selected = reactive(0)
    visible = reactive(False)

    def compose(self) -> ComposeResult:
        yield Static("", id="dropdown-text", markup=True)

    MAX_VISIBLE = 8

    def _render_content(self) -> str:
        if not self.items or not self.visible:
            return ""

        import os as _os
        try:
            _term_cols = _os.get_terminal_size().columns
        except (ValueError, OSError):
            _term_cols = 80
        cols = max(30, min(100, _term_cols - 4))
        lines: list[str] = []
        top = f"[{_BORDER}]┌{'─' * cols}[/]"
        bottom = f"[{_BORDER}]└{'─' * cols}[/]"
        lines.append(top)

        # Scroll window: show max MAX_VISIBLE items centered on selected
        total = len(self.items)
        visible = self.items
        start = 0
        if total > self.MAX_VISIBLE:
            # Center selected in window, clamp to valid range
            half = self.MAX_VISIBLE // 2
            start = max(0, min(self.selected - half, total - self.MAX_VISIBLE))
            end = start + self.MAX_VISIBLE
            visible = self.items[start:end]
            if start > 0:
                lines.append(f"[{_DIM}]  ↑ {start} more above[/]")
            for i, (value, desc) in enumerate(visible):
                real_idx = start + i
                marker = "▸" if real_idx == self.selected else " "
                if real_idx == self.selected:
                    lines.append(f"[{_ACCENT} bold]{marker} {value}[/]  [{_DIM}]{desc}[/]")
                else:
                    lines.append(f"  [{_TEXT}]{value}[/]  [{_DIM}]{desc}[/]")
            if end < total:
                remaining = total - end
                lines.append(f"[{_DIM}]  ↓ {remaining} more below[/]")
        else:
            for i, (value, desc) in enumerate(visible):
                marker = "▸" if i == self.selected else " "
                if i == self.selected:
                    lines.append(f"[{_ACCENT} bold]{marker} {value}[/]  [{_DIM}]{desc}[/]")
                else:
                    lines.append(f"  [{_TEXT}]{value}[/]  [{_DIM}]{desc}[/]")

        lines.append(bottom)
        return "\n".join(lines)

    def _refresh(self) -> None:
        try:
            self.query_one("#dropdown-text", Static).update(self._render_content())
        except Exception:
            pass

    def watch_items(self, v: list) -> None: self._refresh()
    def watch_selected(self, v: int) -> None: self._refresh()
    def watch_visible(self, v: bool) -> None:
        self.styles.display = "block" if v else "none"
        self._refresh()

    def select_next(self) -> None:
        if not self.items:
            return
        self.selected = (self.selected + 1) % len(self.items)

    def select_prev(self) -> None:
        if not self.items:
            return
        self.selected = (self.selected - 1) % len(self.items)

    @property
    def current_value(self) -> str:
        if self.items and 0 <= self.selected < len(self.items):
            return self.items[self.selected][0]
        return ""


# ═══════════════════════════════════════════════════════════════════════
# Role rendering (inline labels, no boxes)
# ═══════════════════════════════════════════════════════════════════════

_ROLE_STYLES: dict[str, tuple[str, str, str]] = {
    "user":       ("▌ User ▐",       _ACCENT,  _ACCENT),
    "assistant":  ("▌ Assistant ▐",  _GREEN,   _TEXT),
    "tool":       ("▌ Tool ▐",       _YELLOW,  _YELLOW),
    "error":      ("▌ Error ▐",      _RED,     _RED),
    "thinking":   ("▌ Think ▐",      _DIM,     _DIM),
    "permission": ("▌ Permit ▐",     _ORANGE,  _ORANGE),
    "system":     ("▌ System ▐",     _DIM,     _DIM),
    "avatar":     ("▌ Avatar ▐",     _CYAN,    _CYAN),
    "roleplay":  ("▌ Rp ▐",       _YELLOW,  _DIM),
    "emotion":    ("▌ Emot ▐",     _PINK,    _PINK),
}


def _fmt_role(text: str, role: str) -> Text:
    tag, tc, tx = _ROLE_STYLES.get(role, ("▌ ? ▐", _DIM, _DIM))
    return Text.assemble(
        (tag, Style(color=tc, dim=True)),
        (" ", Style(dim=True)),
        (text, Style(color=tx)),
    )


def role_text(role: str, text: str) -> Text:
    return _fmt_role(text, role)


def render_user(text: str) -> Text:
    return role_text("user", text)


def render_assistant(text: str) -> Panel:
    return Markdown(text, code_theme="nord", style=_TEXT)


def render_thinking(text: str) -> Text:
    return role_text("thinking", text)


def render_tool(text: str) -> Text:
    return role_text("tool", text)


def render_tool_result(result: str) -> Text:
    body = Text(result, style=_YELLOW)
    if result and result[0] in ("{", "["):
        try:
            parsed = _json.loads(result)
            pretty = _json.dumps(parsed, indent=2, default=str)
            if len(pretty) > 600:
                body = Text(pretty[:600] + "\n… truncated", style=_YELLOW)
            else:
                body = Text(pretty, style=_YELLOW)
        except Exception:
            pass
    return role_text("tool", body.plain)


def render_error(text: str) -> Text:
    """Render an error message with formatting.
    
    Truncates long stack traces and formats cleanly.
    """
    msg = text
    # Truncate overly long error messages
    if len(msg) > 500:
        msg = msg[:500] + "\n… (truncated)"
    return role_text("error", msg)


def render_permission(text: str) -> Text:
    return role_text("permission", text)


def render_system(text: str) -> Text:
    return role_text("system", text)


# ═══════════════════════════════════════════════════════════════════════
# Header
# ═══════════════════════════════════════════════════════════════════════

_STATUS_MAP = {"dev": "DEV", "ready": "READY", "streaming": "STREAMING"}


class AmalgamHeader(Widget):
    """Multi-line centered header with live stats."""
    session_id = reactive("")
    provider   = reactive("")
    model      = reactive("")
    status     = reactive("")
    msg_count  = reactive(0)
    char_count = reactive(0)
    uptime     = reactive("")

    def compose(self) -> ComposeResult:
        yield Static("", id="header-text", markup=True)

    def _short_id(self) -> str:
        s = self.session_id
        return (s[:18] + "…") if len(s) > 18 else s

    def _render_content(self) -> str:
        lines: list[str] = []

        # Top line: session ID + status
        sid = self._short_id()
        status_badge = f" [{_YELLOW}]●{_STATUS_MAP.get(self.status, self.status)}[/{_YELLOW}]" if self.status else ""
        lines.append(f"[{_DIM}]{sid}{status_badge}[/]")

        # Provider/model line
        if self.provider and self.model:
            lines.append(
                f"[{_CYAN}]{self.provider}[/] · "
                f"[{_PINK} bold]{self.model}[/]"
            )
        elif self.model:
            lines.append(f"[{_PINK} bold]{self.model}[/]")

        # Stats line: messages, chars, uptime
        stats_parts = []
        if self.msg_count:
            stats_parts.append(f"[{_GREEN}]{self.msg_count} msgs[/]")
        if self.char_count:
            stats_parts.append(f"[{_CYAN}]{self.char_count:,} chars[/]")
        if self.uptime:
            stats_parts.append(f"[{_DIM}]{self.uptime}[/]")
        if stats_parts:
            lines.append(" · ".join(stats_parts))

        # Quick help
        lines.append(f"[{_DIM}]Esc cancel · Ctrl+N new · /help[/]")

        return "\n".join(lines)

    def _refresh(self) -> None:
        try:
            self.query_one("#header-text", Static).update(self._render_content())
        except Exception:
            pass

    def watch_session_id(self, v: str) -> None: self._refresh()
    def watch_provider(self, v: str) -> None: self._refresh()
    def watch_model(self, v: str) -> None: self._refresh()
    def watch_status(self, v: str) -> None: self._refresh()
    def watch_msg_count(self, v: int) -> None: self._refresh()
    def watch_char_count(self, v: int) -> None: self._refresh()
    def watch_uptime(self, v: str) -> None: self._refresh()


# ═══════════════════════════════════════════════════════════════════════
# Loading / Spinner overlay
# ═══════════════════════════════════════════════════════════════════════

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

class LoadingOverlay(Widget):
    message = reactive("Initializing…")
    _spinner_active = reactive(False)
    _spinner_index = reactive(0)

    def compose(self) -> ComposeResult:
        yield Label("", id="loading-text")

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.1, self._advance_spinner)

    def on_unmount(self) -> None:
        if hasattr(self, '_timer') and self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _advance_spinner(self) -> None:
        if not self._spinner_active:
            return
        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_FRAMES)
        self._update_display()

    def _update_display(self) -> None:
        try:
            label = self.query_one("#loading-text", Label)
            if self._spinner_active:
                frame = _SPINNER_FRAMES[self._spinner_index]
                label.update(f"{frame} {self.message}")
            else:
                label.update(self.message)
        except Exception:
            pass

    def watch_message(self, v: str) -> None:
        self._update_display()

    def start_spinner(self, msg: str = "") -> None:
        if msg:
            self.message = msg
        self._spinner_active = True

    def stop_spinner(self, msg: str = "") -> None:
        self._spinner_active = False
        if msg:
            self.message = msg
        self._update_display()


# ═══════════════════════════════════════════════════════════════════════
# Main App
# ═══════════════════════════════════════════════════════════════════════

class AmalgamTUI(App):
    """Full-screen chat TUI — jcode-inspired design."""

    CSS = """
    Screen {
        background: #1a1b26;
    }

    AmalgamHeader {
        dock: top;
        height: auto;
        background: #24253a;
        border-bottom: solid #3b3d5c;
    }

    #header-text {
        width: 100%;
        text-align: center;
        padding: 1 2;
        height: auto;
    }

    #chat-log {
        height: 1fr;
        background: #1a1b26;
        border: none;
        padding: 1 2;
        overflow-y: scroll;
        scrollbar-gutter: stable;
        scrollbar-color: #2a2b41 auto;
    }

    #dropdown-container {
        dock: bottom;
        height: auto;
        max-height: 15;
        layer: overlay;
        width: 100%;
        background: transparent;
        margin-bottom: 1;
    }

    InlineDropdown {
        background: #24253a;
        border: solid #7aa2f7;
        height: auto;
        padding: 0 1;
        margin: 0 2;
        display: none;
    }

    #dropdown-text {
        padding: 0 1;
        height: auto;
    }

    #input-container {
        dock: bottom;
        height: auto;
        min-height: 1;
        background: #24253a;
        padding: 0 1;
        border-top: solid #3b3d5c;
    }

    #input-area {
        height: auto;
        min-height: 1;
        padding: 0;
    }

    #chat-input {
        background: #24253a;
        color: #c0caf5;
        border: none;
        padding: 0 1;
        min-height: 1;
    }

    #chat-input:focus {
        border: none;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: #24253a;
        color: #565f89;
        padding: 0 2;
        border-top: solid #3b3d5c;
    }

    #loading-overlay {
        dock: top;
        height: 5;
        background: #1a1b26;
        align: center middle;
    }

    #loading-text {
        color: #565f89;
        text-style: italic;
    }

    #stream-area {
        height: auto;
        max-height: 12;
        background: #1a1b26;
        color: #9ece6a;
        padding: 0 2;
        border: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+d", "quit", "Quit", priority=True),
        Binding("ctrl+n", "new_session", "New", priority=True),
        Binding("ctrl+l", "clear_screen", "Clear", priority=True),
        Binding("escape", "cancel_or_hide_dropdown", "Cancel", priority=True),
        Binding("up", "dropdown_up", "Up", priority=True),
        Binding("down", "dropdown_down", "Down", priority=True),
    ]

    def __init__(
        self,
        settings: Any = None,
        llm: Any = None,
        memory: Any = None,
        agent: Any = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._settings = settings
        self._llm = llm
        self._memory = memory
        self._agent = agent
        self._show_thinking = True
        self._last_message = ""
        self._backend_loading = settings is None
        self._backend_failed = False
        self._streaming = False
        self._dropdown_mode = "command"  # "command", "provider", "model"
        self._all_dropdown_items: list[tuple[str, str]] = []
        self._skip_change = False
        self._pending_api_key_for: tuple[str, str] | None = None  # (action, provider_name)
        self._stream_task: asyncio.Task | None = None
        self._last_filter_prefix: str = ""
        self._msg_count = 0
        self._char_count = 0
        self._start_time = __import__("time").time()

    def compose(self) -> ComposeResult:
        yield AmalgamHeader()
        yield RichLog(id="chat-log", highlight=True, markup=True, min_width=40)
        yield InlineDropdown(id="inline-dropdown")
        yield Container(
            Container(
                Input(id="chat-input", placeholder=""),
                id="input-area",
            ),
            id="input-container",
        )
        yield Container(Label(""), id="status-bar")
        yield RichLog(id="stream-area", highlight=False, markup=False)
        yield LoadingOverlay(id="loading-overlay")

    def on_mount(self) -> None:
        # Apply theme palette from settings or default
        if self._settings:
            try:
                theme = self._settings.get("ui.theme", "dark")
            except Exception:
                theme = "dark"
        else:
            theme = "dark"
        _apply_palette(theme)
        self._apply_css_theme()

        if self._backend_loading:
            self._show_loading("Initializing backend…")
            self.query_one("#chat-input", Input).disabled = True
            self._update_status("Initializing…")
        else:
            self._update_header()
            self._log_system(f"Welcome — {self._short_id()}")
            self.query_one("#chat-input", Input).focus()

    def _apply_css_theme(self) -> None:
        """Override hardcoded CSS colors with the active palette at runtime."""
        try:
            self.screen.styles.background = _BG
        except Exception:
            pass
        for wid in ["#chat-log", "#loading-overlay", "#stream-area"]:
            try:
                self.query_one(wid).styles.background = _BG
            except Exception:
                pass
        for wid in ["#input-container", "#status-bar"]:
            try:
                self.query_one(wid).styles.background = _SURFACE
            except Exception:
                pass
        try:
            inp = self.query_one("#chat-input")
            inp.styles.background = _SURFACE
            inp.styles.color = _TEXT
        except Exception:
            pass
        try:
            sb = self.query_one("#status-bar")
            sb.styles.color = _DIM
            sb.styles.border_top = ("solid", _BORDER)
        except Exception:
            pass
        try:
            inp_c = self.query_one("#input-container")
            inp_c.styles.border_top = ("solid", _BORDER)
        except Exception:
            pass
        try:
            header = self.query_one(AmalgamHeader)
            header.styles.background = _SURFACE
            header.styles.border_bottom = ("solid", _BORDER)
        except Exception:
            pass

    # ── Lifecycle ──────────────────────────────────────────────────────

    def set_backend(self, settings, llm, memory, agent) -> None:
        self._settings = settings
        self._llm = llm
        self._memory = memory
        self._agent = agent
        self._backend_loading = False
        self._hide_loading()
        self._update_header()
        self._log_system(f"Ready — {self._short_id()}")

        # Prevent clicks in the chat log from stealing focus
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.can_focus = False

        input_w = self.query_one("#chat-input", Input)
        input_w.disabled = False
        input_w.placeholder = "Type a message…"
        input_w.focus()
        self._update_status("Ctrl+Q quit · Ctrl+N new · /help")

    def show_error(self, msg: str) -> None:
        self._backend_loading = False
        self._backend_failed = True
        self._hide_loading()
        self._log_error(msg)
        self._update_header()
        self._update_status(f" ERROR: {msg}")
        self.query_one("#chat-input", Input).placeholder = "Backend failed — check settings"

    # ── Loading / Spinner ──────────────────────────────────────────────

    def _show_loading(self, msg: str) -> None:
        try:
            ov = self.query_one("#loading-overlay", LoadingOverlay)
            ov.styles.display = "block"
            ov.start_spinner(msg)
        except Exception:
            log.warning("Failed to show loading overlay", exc_info=True)

    def _hide_loading(self) -> None:
        try:
            ov = self.query_one("#loading-overlay", LoadingOverlay)
            ov.stop_spinner()
            ov.styles.display = "none"
        except Exception:
            pass

    # ── Header ─────────────────────────────────────────────────────────

    def _sid(self) -> str:
        try:
            return self._memory.get_current_session() if self._memory else ""
        except Exception:
            return ""

    def _short_id(self) -> str:
        s = self._sid()
        return (s[:22] + "…") if len(s) > 22 else s

    def _prov(self) -> str:
        try:
            return (self._settings.get("provider.active", "") if self._settings else "")
        except Exception:
            return ""

    def _model(self) -> str:
        try:
            p = self._prov()
            return (self._settings.get(f"provider.{p}.model", "") if p and self._settings else "")
        except Exception:
            return ""

    def _update_header(self) -> None:
        try:
            h = self.query_one(AmalgamHeader)
            h.session_id = self._sid()
            h.provider = self._prov()
            h.model = self._model()
            h.status = "dev" if self._backend_loading else ""
        except Exception:
            pass

    # ── Status bar ─────────────────────────────────────────────────────

    def _update_status(self, text: str) -> None:
        try:
            sb = self.query_one("#status-bar", Container)
            sb.remove_children()
            sb.mount(Label(text))
        except Exception:
            log.warning("Failed to update status bar", exc_info=True)

    # ── Logging ─────────────────────────────────────────────────────────

    def _log_chat(self, content, *, role: str | None = None) -> None:
        chat = self.query_one("#chat-log", RichLog)
        if isinstance(content, (Text, Markdown, Table, Panel)):
            chat.write(content)
        elif isinstance(content, str):
            if role:
                chat.write(role_text(role, content))
            else:
                chat.write(Text(content, style=_TEXT))

    def _log_system(self, text: str) -> None: self._log_chat(render_system(text))
    def _log_error(self, text: str) -> None: self._log_chat(render_error(text))
    def _log_user(self, text: str) -> None: self._log_chat(render_user(text))
    def _log_assistant(self, text: str) -> None: self._log_chat(render_assistant(text))
    def _log_thinking(self, text: str) -> None: self._log_chat(render_thinking(text))
    def _log_tool(self, text: str) -> None: self._log_chat(render_tool(text))

    def _log_stream_chunk(self, text: str) -> None:
        try:
            self.query_one("#stream-area", RichLog).write(Text(text, style=_GREEN))
        except Exception:
            self._log_chat(Text(text, style=_GREEN))

    def _clear_stream_area(self) -> None:
        try:
            self.query_one("#stream-area", RichLog).clear()
        except Exception:
            pass

    # ── Dropdown (inline command picker) ───────────────────────────────

    def _is_dropdown_visible(self) -> bool:
        try:
            dd = self.query_one("#inline-dropdown", InlineDropdown)
            return dd.visible
        except Exception:
            return False

    def _show_dropdown(self, mode: str, items: list[tuple[str, str]], filter_text: str = "") -> None:
        """Show the inline dropdown with filtered items."""
        self._dropdown_mode = mode
        self._all_dropdown_items = items

        dd = self.query_one("#inline-dropdown", InlineDropdown)
        if filter_text:
            values = [v for v, _ in items]
            desc_map = dict(items)
            matched = fuzzy_filter(filter_text, values)
            filtered = [(v, desc_map.get(v, "")) for v in matched]
        else:
            filtered = list(items)

        dd.items = filtered
        dd.selected = 0
        dd.visible = True

    def _hide_dropdown(self) -> None:
        try:
            dd = self.query_one("#inline-dropdown", InlineDropdown)
            dd.visible = False
            dd.items = []
        except Exception:
            pass

    def _rebuild_dropdown_filter(self, prefix: str) -> None:
        """Rebuild dropdown items based on the typed prefix after /."""
        if not self._all_dropdown_items:
            return

        values = [v for v, _ in self._all_dropdown_items]
        desc_map = dict(self._all_dropdown_items)
        matched = fuzzy_filter(prefix, values)
        filtered = [(v, desc_map.get(v, "")) for v in matched]
        dd = self.query_one("#inline-dropdown", InlineDropdown)
        dd.items = filtered
        if prefix != self._last_filter_prefix or dd.selected >= len(filtered):
            dd.selected = 0
        self._last_filter_prefix = prefix

    def _select_dropdown_item(self) -> None:
        """Autocomplete the selected dropdown item into the input."""
        dd = self.query_one("#inline-dropdown", InlineDropdown)
        if not dd.items or not dd.visible:
            return
        value = dd.current_value
        if not value:
            return

        inp = self.query_one("#chat-input", Input)
        self._hide_dropdown()

        if self._dropdown_mode == "command":
            inp.value = value + " "
            # Don't skip on_input_changed — it will detect the space and
            # show the arg dropdown for /provider and /model automatically
        elif self._dropdown_mode == "provider":
            self._skip_change = True
            current_input = inp.value
            cur_parts = current_input.split(maxsplit=2)
            if len(cur_parts) >= 2 and cur_parts[1].lower() in ("add", "set", "rm"):
                # Preserve existing subcommand, replace provider name only
                inp.value = f"/provider {cur_parts[1]} {value} "
            else:
                inp.value = f"/provider {value} "
        elif self._dropdown_mode == "model":
            self._skip_change = True
            inp.value = f"/model {value} "
        elif self._dropdown_mode == "theme":
            self._skip_change = True
            inp.value = f"/theme {value} "
        elif self._dropdown_mode == "profile":
            self._skip_change = True
            inp.value = f"/profile {value} "
        elif self._dropdown_mode == "permission":
            self._skip_change = True
            inp.value = f"/permission {value} "
        elif self._dropdown_mode == "character":
            self._skip_change = True
            inp.value = f"/character {value} "
        elif self._dropdown_mode == "settings":
            self._skip_change = True
            inp.value = f"/settings {value} "

        inp.cursor_position = len(inp.value)
        inp.focus()

    # ── Input ──────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()

        # If dropdown is visible, autocomplete instead of submit
        if self._is_dropdown_visible():
            self._select_dropdown_item()
            return

        # If we're waiting for an API key, capture it (even empty = cancel)
        if self._pending_api_key_for:
            action, name = self._pending_api_key_for
            self._pending_api_key_for = None
            inp = self.query_one("#chat-input", Input)
            inp.password = False
            inp.clear()
            inp.placeholder = "Type a message…"
            self._update_status("Ctrl+Q quit · Ctrl+N new · /help")
            if text:
                self._settings.set(f"provider.{name}.api_key", text)
                self._log_system(f"API key {'updated' if action == 'set' else 'added'} for {name}")
                # Auto-switch to this provider if none is active
                if not self._prov():
                    self._set_provider(name)
            else:
                self._log_system("API key entry cancelled")
            return

        if not text:
            return
        self.query_one("#chat-input", Input).clear()

        if text.startswith("/"):
            self._handle_command(text)
            return

        if text == "/retry" and self._last_message:
            text = self._last_message
        else:
            self._last_message = text

        self._log_user(text)
        self._clear_stream_area()
        self._send_message(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Show/hide/filter the inline dropdown when typing /.

        - Type '/' → command dropdown
        - Type space after a command → arg dropdown:
            /provider → [add, set, rm], then provider names
            /model    → models from all configured providers
        - Type letters → filter the current dropdown
        - Backspace past the space → back to command dropdown
        """
        if self._skip_change:
            self._skip_change = False
            return

        raw = event.value
        stripped = raw.strip()

        # Not a command prefix → hide dropdown
        if not stripped.startswith("/"):
            self._hide_dropdown()
            return

        # Check if there's a space → arg completion mode
        if " " in raw:
            cmd_part, _, after_first = raw.partition(" ")
            cmd_part = cmd_part.strip().lower()

            if cmd_part == "/provider":
                # Two-level arg: /provider [add|set|rm] [name]
                after = after_first.strip()
                # Detect if user has typed a subcommand and now typing provider
                subcmd = None
                for sc in ("add", "set", "rm"):
                    if after == sc or after.startswith(sc + " "):
                        subcmd = sc
                        break

                if subcmd is not None:
                    # Show provider names, but if a complete exact provider name
                    # is already typed, hide dropdown so Enter executes the command.
                    prov_prefix = after[len(subcmd):].strip()
                    if subcmd == "add":
                        from backend.core.deps import get_shared
                        items = [(p, "") for p in get_shared()["known_providers"]]
                    else:  # set, rm
                        providers = get_detected_providers(self._settings)
                        items = [(p, "") for p in providers]

                    if prov_prefix:
                        exact = [v for v, _ in items if v.lower() == prov_prefix.lower()]
                        if exact and not raw.endswith(" "):
                            # Exact provider name typed → hide dropdown so Enter executes
                            self._hide_dropdown()
                            return

                    self._show_dropdown("provider", items, prov_prefix)
                else:
                    # Check if the user typed a provider name directly
                    # (legacy /provider <name> without subcommand).
                    from backend.core.deps import get_shared
                    _providers = get_shared()["known_providers"]
                    after_lower = after.strip().lower()
                    if after_lower and after_lower not in ("add", "set", "rm"):
                        # Only hide if it looks like a provider name
                        # (any non-empty text that isn't a subcommand).
                        # This lets the user type /provider ollama and
                        # press Enter without an empty dropdown blocking it.
                        self._hide_dropdown()
                        return
                    # Show subcommands
                    items = [
                        ("add", "Add API key"),
                        ("set", "Update API key"),
                        ("rm", "Remove API key"),
                    ]
                    self._show_dropdown("provider", items, after)

            elif cmd_part == "/model":
                # Fetch live models from backend API, fall back to hardcoded list
                items = []
                active_provider = self._prov()
                if active_provider:
                    try:
                        import urllib.request, json as _json
                        _backend_host = os.environ.get("AMALGAM_HOST", "localhost")
                        _backend_port = os.environ.get("AMALGAM_PORT", "8000")
                        url = f"http://{_backend_host}:{_backend_port}/api/models/{active_provider}"
                        req = urllib.request.Request(url, headers={"Accept": "application/json"})
                        with urllib.request.urlopen(req, timeout=3) as resp:
                            data = _json.loads(resp.read())
                            live_models = data.get("models", [])
                            if live_models:
                                items = [(m, "") for m in live_models]
                    except Exception:
                        pass  # fallback below

                # Fallback to hardcoded list
                if not items:
                    from backend.core.deps import get_shared
                    models_map = get_shared()["provider_models"]
                    _rev_map = {"chatgpt": "openai", "claude": "anthropic"}
                    model_key = _rev_map.get(active_provider, active_provider)
                    models = get_models_for_provider(self._settings, model_key) or models_map.get(model_key, [])
                    items = [(m, "") for m in models]

                if not items:
                    self._log_system(f"No models available for {active_provider or '(none)'}. Use /model <name> to set manually.")
                    self._hide_dropdown()
                    return

                # If exact model name already typed, hide dropdown so Enter executes
                model_prefix = after_first.strip()
                if model_prefix:
                    exact = [v for v, _ in items if v == model_prefix.strip()]
                    if exact and not raw.endswith(" "):
                        self._hide_dropdown()
                        return

                self._show_dropdown("model", items, after_first.strip())

            elif cmd_part == "/theme":
                themes = [
                    ("dark", "Dark theme"),
                    ("midnight", "Midnight theme"),
                    ("light", "Light theme"),
                    ("nord", "Nord theme"),
                ]
                after = after_first.strip()
                # Hide if exact theme typed
                if after:
                    exact = [v for v, _ in themes if v == after.strip().lower()]
                    if exact and not raw.endswith(" "):
                        self._hide_dropdown()
                        return
                self._show_dropdown("theme", themes, after)

            elif cmd_part == "/profile":
                profiles = [
                    ("default", "Default profile"),
                    ("token-friendly", "Token-efficient profile"),
                    ("quality", "Quality-focused profile"),
                    ("custom", "Custom profile"),
                ]
                after = after_first.strip()
                if after:
                    exact = [v for v, _ in profiles if v == after.strip().lower()]
                    if exact and not raw.endswith(" "):
                        self._hide_dropdown()
                        return
                self._show_dropdown("profile", profiles, after)

            elif cmd_part == "/permission":
                levels = [
                    ("readonly", "Read-only mode"),
                    ("confirm", "Ask before executing"),
                    ("full", "Full access"),
                ]
                after = after_first.strip()
                if after:
                    exact = [v for v, _ in levels if v == after.strip().lower()]
                    if exact and not raw.endswith(" "):
                        self._hide_dropdown()
                        return
                self._show_dropdown("permission", levels, after)

            elif cmd_part == "/character":
                char_items = []
                if self._settings:
                    chars = get_detected_providers(self._settings)
                try:
                    from backend.core.deps import get_shared
                    chars_dir = get_shared()["characters_dir"]
                    import os
                    if os.path.isdir(str(chars_dir)):
                        for d in sorted(os.listdir(str(chars_dir))):
                            if os.path.isdir(os.path.join(str(chars_dir), d)):
                                char_items.append((d, ""))
                except Exception:
                    pass
                if not char_items:
                    char_items = [("default", "Default character")]
                after = after_first.strip()
                if after:
                    exact = [v for v, _ in char_items if v == after.strip().lower()]
                    if exact and not raw.endswith(" "):
                        self._hide_dropdown()
                        return
                self._show_dropdown("character", char_items, after)

            elif cmd_part == "/settings":
                # Show common setting keys
                common_keys = [
                    ("provider.active", "Active provider"),
                    ("voice.engine", "TTS engine"),
                    ("voice.stt_engine_cli", "STT engine (CLI)"),
                    ("voice.input_enabled", "Voice input toggle"),
                    ("voice.output_enabled", "Voice output toggle"),
                    ("ui.theme", "UI theme"),
                    ("ui.font_size", "Font size"),
                    ("ui.language", "Language"),
                    ("ui.accent_color", "Accent color"),
                    ("profile", "Settings profile"),
                    ("character.active", "Active character"),
                    ("agent.type", "Agent type"),
                    ("llm.temperature", "Temperature"),
                    ("vault.path", "Vault path"),
                    ("wake_word.engine", "Wake word engine"),
                    ("mcp.servers", "MCP servers"),
                ]
                after = after_first.strip()
                if after:
                    # Filter by prefix
                    filtered = [(v, d) for v, d in common_keys if v.startswith(after)]
                    if not filtered:
                        self._hide_dropdown()
                        return
                    self._show_dropdown("settings", filtered, after)
                else:
                    self._show_dropdown("settings", common_keys, "")

            elif cmd_part in ("/rename",):
                # Accept any free-text arg — don't show dropdown
                self._hide_dropdown()

            else:
                # Unhandled command → hide dropdown
                self._hide_dropdown()
        else:
            # No space → command prefix mode
            prefix = stripped[1:]  # what comes after /
            mode = "command"
            _init_command_registry()
            cmds = get_slash_commands()
            items = []
            for c in cmds:
                desc = _COMMAND_DEFS.get(c, ("", "", None))[0]
                if desc:
                    items.append((c, desc))

            if self._is_dropdown_visible() and self._dropdown_mode == mode:
                self._rebuild_dropdown_filter(prefix)
            else:
                self._show_dropdown(mode, items, prefix)

    # ── Keyboard actions ───────────────────────────────────────────────

    def action_cancel_or_hide_dropdown(self) -> None:
        if self._is_dropdown_visible():
            self._hide_dropdown()
        elif self._streaming:
            self._cancel_stream()

    def action_dropdown_up(self) -> None:
        try:
            dd = self.query_one("#inline-dropdown", InlineDropdown)
            if dd.visible:
                dd.select_prev()
        except Exception:
            pass

    def action_dropdown_down(self) -> None:
        try:
            dd = self.query_one("#inline-dropdown", InlineDropdown)
            if dd.visible:
                dd.select_next()
        except Exception:
            pass

    def _handle_command(self, text: str) -> None:
        cmd = text.split()[0].lower()

        if cmd in ("/exit", "/quit"):
            self.exit()

        elif cmd in ("/new", "/clear"):
            self.query_one("#chat-log", RichLog).clear()
            self._clear_stream_area()
            if cmd == "/new":
                try:
                    if self._memory:
                        self._memory.start_session()
                except Exception as e:
                    self._log_error(f"Failed to start session: {e}")
            self._update_header()
            self._log_system("New session" if cmd == "/new" else "Cleared")

        elif cmd == "/help":
            self._show_help()

        elif cmd == "/think":
            parts = text.split(maxsplit=1)
            arg = parts[1].lower() if len(parts) > 1 else ""
            if arg == "on":
                new_state = True
            elif arg == "off":
                new_state = False
            elif arg == "":
                new_state = not self._show_thinking
            else:
                self._log_system("Usage: /think [on|off]")
                return
            self._show_thinking = new_state
            self._log_system(f"Thinking: {'ON' if self._show_thinking else 'OFF'}")

        elif cmd == "/provider":
            # Use partition to preserve multi-word provider names
            _, _, rest = text.partition(" ")
            rest = rest.strip()
            if not rest:
                current = self._prov() or "?"
                self._log_system(f"Current provider: {current}")
                return
            subcmd, _, name = rest.partition(" ")
            if subcmd.lower() in ("add", "set", "rm"):
                if name:
                    self._handle_provider_key(subcmd.lower(), name.lower())
                else:
                    self._log_system(f"Usage: /provider {subcmd.lower()} <name>")
            else:
                # Legacy: just switch active provider
                self._set_provider(rest.lower())

        elif cmd == "/model":
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                self._set_model(parts[1])
            else:
                current = self._model() or "?"
                p = self._prov() or "?"
                try:
                    from backend.core.deps import get_shared
                    known_models = get_shared()["provider_models"]
                    known = known_models.get(p, [])
                    if known:
                        self._log_system(f"Current model ({p}): {current}\nKnown: {', '.join(known)}")
                    else:
                        self._log_system(f"Current model ({p}): {current}")
                except Exception:
                    self._log_system(f"Current model ({p}): {current}")

        elif cmd == "/rename":
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                try:
                    if self._memory:
                        sid = self._memory.get_current_session()
                        self._memory.rename_session(sid, parts[1])
                        self._log_system(f"Renamed to: {parts[1]}")
                except Exception as e:
                    self._log_error(f"Rename failed: {e}")
            else:
                self._log_system("Usage: /rename <new-title>")

        elif cmd == "/resume":
            try:
                if self._memory:
                    sid = self._memory.get_current_session()
                    turns = self._memory.get_session_turns(sid, turns=5)
                    self._log_system(f"Last 5 turns of {sid}:")
                    for turn in turns:
                        role = turn.get("role", "?").lower()
                        content = turn.get("content", "")
                        self._log_chat(role_text(role, content[:200]))
            except Exception as e:
                self._log_error(f"Resume failed: {e}")

        elif cmd == "/compact":
            self._log_system("Forcing memory compaction…")
            try:
                if self._memory:
                    if hasattr(self._memory, 'check_and_summarize'):
                        self.run_worker(self._do_compact())
                    elif hasattr(self._memory, 'compact'):
                        self._memory.compact()
                        self._log_system("Memory compacted")
                    else:
                        self._log_error("Memory backend does not support compaction")
            except Exception as e:
                self._log_error(f"Compaction failed: {e}")

        elif cmd == "/health":
            self._show_health()

        elif cmd == "/companion":
            parts = text.split(maxsplit=1)
            arg = parts[1].lower() if len(parts) > 1 else ""
            self._toggle_companion(arg)

        elif cmd == "/settings":
            self._show_or_set_settings(text)

        elif cmd == "/memory":
            self._show_memory_stats()

        elif cmd == "/stats":
            self._show_stats()

        elif cmd == "/theme":
            self._switch_theme(text)

        elif cmd == "/character":
            self._switch_character(text)

        elif cmd == "/profile":
            self._switch_profile(text)

        elif cmd == "/permission":
            self._set_permission(text)

        else:
            from cli.__init__ import _fuzzy_command_suggestion
            sug = _fuzzy_command_suggestion(text)
            if sug:
                self._log_error(f"Unknown: {text} — try {sug}?")
            elif text.startswith("/"):
                self._log_error(f"Unknown command: {text}")

    def _set_provider(self, name: str) -> None:
        from backend.core.deps import get_shared
        _known_providers = get_shared()["known_providers"]
        if name not in _known_providers:
            fuzzy = [p for p in _known_providers if p.startswith(name.lower())]
            hint = f" — try {fuzzy[0]}?" if fuzzy else ""
            self._log_error(f"Unknown provider: {name}{hint}")
            return
        _name_map = {
            "openai": "chatgpt",
            "anthropic": "claude",
        }
        config_key = _name_map.get(name, name)
        if self._settings:
            try:
                self._settings.set("provider.active", config_key)
                if self._llm:
                    self._llm.reload_settings()
                self._update_header()
                self._log_system(f"Provider → {name}")
            except Exception as e:
                self._log_error(f"Cannot set provider: {e}")

    def _handle_provider_key(self, action: str, name: str) -> None:
        """Handle /provider add|set|rm <name>."""
        from backend.core.deps import get_shared
        _known_providers = get_shared()["known_providers"]
        if name not in _known_providers:
            fuzzy = [p for p in _known_providers if p.startswith(name)]
            hint = f" — try {fuzzy[0]}?" if fuzzy else ""
            self._log_error(f"Unknown provider: {name}{hint}")
            return

        if action == "rm":
            if self._settings:
                try:
                    cfg = self._settings.get(f"provider.{name}")
                    if isinstance(cfg, dict) and cfg.get("api_key"):
                        del cfg["api_key"]
                        self._settings.set(f"provider.{name}", cfg)
                        self._log_system(f"API key removed for {name}")
                    else:
                        self._log_system(f"No API key found for {name}")
                except Exception as e:
                    self._log_error(f"Failed to remove key: {e}")
        else:  # add, set
            inp = self.query_one("#chat-input", Input)
            inp.password = True
            inp.placeholder = f"Enter API key for {name}:"
            inp.clear()
            self._update_status(f"Type API key for {name} and press Enter")
            self._pending_api_key_for = (action, name)

    def _set_model(self, name: str) -> None:
        p = self._prov()
        if self._settings and p:
            try:
                self._settings.set(f"provider.{p}.model", name)
                if self._llm:
                    self._llm.reload_settings()
                self._update_header()
                self._log_system(f"Model → {name}")
            except Exception as e:
                self._log_error(f"Cannot set model: {e}")

    def _show_help(self) -> None:
        _init_command_registry()
        cmds = get_slash_commands()
        tbl = Table(box=box.SIMPLE, show_header=False, style=_DIM)
        tbl.add_column("Command", style=_CYAN)
        tbl.add_column("Description", style=_TEXT)
        for c in cmds:
            desc = _COMMAND_DEFS.get(c, ("", "", None))[0]
            if desc:
                tbl.add_row(c, desc)
        self._log_chat(tbl)

    def _show_health(self) -> None:
        """Run live health checks and display results."""
        self._log_system("Running health checks…")
        self.run_worker(self._do_health_checks(), exclusive=True)

    async def _do_compact(self) -> None:
        """Async memory compaction via check_and_summarize."""
        try:
            await self._memory.check_and_summarize()
            self._log_system("Memory compacted")
        except Exception as e:
            self._log_error(f"Compaction failed: {e}")

    async def _do_health_checks(self) -> None:
        try:
            from backend.core.deps import get_shared
            registry = get_shared()["health_registry"]
            results = await registry.check_all()
            if results:
                tbl = Table(box=box.SIMPLE, show_header=True, style=_DIM,
                            header_style=Style(color=_ACCENT))
                tbl.add_column("Service", style=_CYAN)
                tbl.add_column("Status")
                tbl.add_column("Detail", style=_DIM)
                for name, s in sorted(results.items()):
                    st = s.get("status", "?")
                    color = {"ok": _GREEN, "degraded": _YELLOW,
                             "down": _RED, "not_configured": _DIM,
                             "unknown": _DIM}.get(st, _DIM)
                    tbl.add_row(name, f"[{color}]{st}[/{color}]",
                                f"[dim]{s.get('detail', '')}[/dim]")
                self._log_chat(tbl)
            else:
                self._log_system("No health data available")
        except Exception as e:
            self._log_error(f"Health check failed: {e}")

    def _toggle_companion(self, arg: str = "") -> None:
        """Toggle, enable, or disable companion mode (voice + avatar).

        Arg: "on", "off", or "" to toggle.
        """
        if not self._settings:
            self._log_error("Settings not available")
            return
        try:
            if arg == "on":
                new_state = True
            elif arg == "off":
                new_state = False
            elif arg == "":
                new_state = not self._settings.get("voice.input_enabled", False)
            else:
                self._log_system("Usage: /companion [on|off]")
                return
            self._settings.set("voice.input_enabled", new_state)
            self._settings.set("voice.output_enabled", new_state)
            self._log_system(f"Companion mode {'ON' if new_state else 'OFF'}")
        except Exception as e:
            self._log_error(f"Companion toggle failed: {e}")


    def _show_or_set_settings(self, text: str) -> None:
        """Show or set a setting value."""
        if not self._settings:
            self._log_error("Settings not available")
            return
        try:
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                args = parts[1].strip().split(" ", 1)
                key = args[0]
                val = args[1] if len(args) > 1 else None
                if val:
                    self._settings.set(key, val)
                    self._update_header()
                    self._log_system(f"Set {key} = {val}")
                else:
                    v = self._settings.get(key, "not set")
                    self._log_system(f"{key} = {v}")
            else:
                # Show key settings
                keys = ["provider.active", "ui.theme", "ui.mode", "voice.engine", "voice.stt_engine_cli", "profile"]
                tbl = Table(box=box.SIMPLE, show_header=False, style=_DIM)
                tbl.add_column("", style=_CYAN)
                tbl.add_column("", style=_TEXT)
                for k in keys:
                    v = self._settings.get(k, "not set")
                    tbl.add_row(k, str(v))
                tbl.add_row("", "[dim]Use /settings <key> <val> to set[/dim]")
                self._log_chat(tbl)
        except Exception as e:
            self._log_error(f"Settings error: {e}")

    def _show_memory_stats(self) -> None:
        """Show memory usage statistics."""
        if not self._memory:
            self._log_error("Memory not available")
            return
        try:
            sessions = self._memory.get_sessions()
            current = self._memory.get_current_session()
            total_msgs = sum(s.get("message_count", 0) for s in sessions)
            tbl = Table(box=box.SIMPLE, show_header=False, style=_DIM)
            tbl.add_column("", style=_CYAN)
            tbl.add_column("", style=_TEXT)
            tbl.add_row("Sessions", str(len(sessions)))
            tbl.add_row("Total messages", str(total_msgs))
            tbl.add_row("Current session", current)
            self._log_chat(tbl)
        except Exception as e:
            self._log_error(f"Memory stats failed: {e}")

    def _show_stats(self) -> None:
        """Show tool-usage analytics."""
        self.run_worker(self._do_stats(), exclusive=True)

    async def _do_stats(self) -> None:
        try:
            from backend.core.deps import get_shared
            collector = get_shared()["metrics_collector"]
            r = await collector.report(days=7)
            tbl = Table(box=box.SIMPLE, show_header=False, style=_DIM)
            tbl.add_column("", style=_CYAN)
            tbl.add_column("", style=_TEXT)
            tbl.add_row("Turns", str(r.get("total_turns", 0)))
            tbl.add_row("Cost", f"${r.get('total_cost_usd', 0):.4f} USD")
            tbl.add_row("Tokens", f"{r.get('total_tokens', 0):,}")
            tbl.add_row("Avg latency", f"{r.get('avg_latency_ms', 0):.0f} ms")
            tbl.add_row("Tool calls", str(r.get("total_tool_calls", 0)))
            self._log_chat(tbl)
        except Exception as e:
            self._log_error(f"Stats unavailable: {e}")

    def _switch_theme(self, text: str) -> None:
        """Switch UI theme and apply it live."""
        _valid = {"dark", "midnight", "light", "nord"}
        if not self._settings:
            self._log_error("Settings not available")
            return
        try:
            parts = text.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip().lower() in _valid:
                theme = parts[1].strip().lower()
                self._settings.set("ui.theme", theme)
                _apply_palette(theme)
                self._apply_css_theme()
                self._update_header()
                self._log_system(f"Theme → {theme}")
            else:
                current = self._settings.get("ui.theme", "dark")
                self._log_system(f"Current theme: {current}\nValid: {', '.join(sorted(_valid))}")
        except Exception as e:
            self._log_error(f"Theme switch failed: {e}")

    def _switch_character(self, text: str) -> None:
        """Switch active character."""
        if not self._settings:
            self._log_error("Settings not available")
            return
        try:
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                name = parts[1].strip()
                try:
                    from backend.core.deps import get_shared
                    chars_dir = get_shared()["characters_dir"]
                    char_dir = str(chars_dir / name)
                    import os
                    if os.path.isdir(char_dir):
                        self._settings.set("character.active", name)
                        self._log_system(f"Character → {name}")
                    else:
                        chars = [d for d in os.listdir(str(chars_dir))
                                 if os.path.isdir(os.path.join(str(chars_dir), d))]
                        self._log_error(f"Character '{name}' not found. Available: {', '.join(chars)}")
                except Exception as e:
                    self._log_error(f"Character error: {e}")
            else:
                current = self._settings.get("character.active", "default")
                self._log_system(f"Current character: {current}")
        except Exception as e:
            self._log_error(f"Character switch failed: {e}")

    def _switch_profile(self, text: str) -> None:
        """Switch settings profile."""
        _valid = {"token-friendly", "default", "quality", "custom"}
        if not self._settings:
            self._log_error("Settings not available")
            return
        try:
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                name = parts[1].strip()
                if name not in _valid:
                    self._log_error(f"Invalid profile: {name}. Valid: {', '.join(sorted(_valid))}")
                    return
                try:
                    from backend.core.deps import get_shared
                    get_shared()["switch_profile"](name)
                    self._update_header()
                    self._log_system(f"Profile → {name}")
                except ValueError as e:
                    self._log_error(f"Profile error: {e}")
            else:
                current = self._settings.get("profile", "default")
                self._log_system(f"Current profile: {current}")
        except Exception as e:
            self._log_error(f"Profile switch failed: {e}")


    def _set_permission(self, text: str) -> None:
        """Set permission level."""
        _valid = {"readonly", "confirm", "full"}
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or parts[1].strip().lower() not in _valid:
            self._log_system(f"Usage: /permission [{'|'.join(sorted(_valid))}]")
            return
        level = parts[1].strip().lower()
        try:
            from backend.core.deps import get_shared
            shared = get_shared()
            mcp = shared.get("mcp")
            if mcp and hasattr(mcp, 'set_permission_level'):
                mcp.set_permission_level(level)
                self._log_system(f"Permission level → {level}")
            else:
                self._log_system(f"Permission level → {level} (local only)")
        except Exception as e:
            self._log_error(f"Permission set failed: {e}")

    # ── Agent streaming ─────────────────────────────────────────────────

    @textual_work(thread=False, exit_on_error=False)
    async def _send_message(self, text: str) -> None:
        if not self._agent:
            self._log_error("Agent not available")
            return

        self._streaming = True
        self._stream_task = asyncio.current_task()
        self._update_status("Streaming… (Esc to cancel)")

        full_response = ""
        try:
            stream: AsyncIterator = self._agent.handle_user_input(text)
            async for chunk in stream:
                if isinstance(chunk, tuple):
                    tag, val = chunk
                    self._handle_tag(tag, val)
                elif isinstance(chunk, str) and chunk.strip():
                    full_response += chunk
                    self._log_stream_chunk(chunk)
            # Persist the full response to chat log
            if full_response.strip():
                self._log_assistant(full_response.strip())
        except asyncio.CancelledError:
            self._log_system("Canceled")
        except Exception as e:
            self._log_error(str(e))
        finally:
            self._streaming = False
            self._stream_task = None
            self._clear_stream_area()
            self._update_status("Ctrl+Q quit · Ctrl+N new · /help")
            self._log_system("─" * 30)

    def _handle_tag(self, tag: str, val: str) -> None:
        if tag == "__thinking__":
            if self._show_thinking:
                self._log_thinking(val)
        elif tag == "__tool__":
            self._log_tool(val)
        elif tag == "__error__":
            self._log_error(val)
        elif tag == "__permission__":
            self._log_chat(role_text("permission", val))
        elif tag == "__roleplay__":
            self._log_chat(role_text("roleplay", val))
        elif tag == "__avatar__":
            self._log_chat(role_text("avatar", val))
        elif tag == "__emotion__":
            self._log_chat(role_text("emotion", val))

    def _cancel_stream(self) -> None:
        self._streaming = False
        if self._stream_task is not None:
            self._stream_task.cancel()
            self._stream_task = None

    # ── Actions ─────────────────────────────────────────────────────────

    def action_new_session(self) -> None: self._handle_command("/new")
    def action_clear_screen(self) -> None: self._handle_command("/clear")

    def action_cancel(self) -> None:
        if self._streaming:
            self._cancel_stream()
