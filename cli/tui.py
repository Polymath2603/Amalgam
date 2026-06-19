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
        ("session",  "Show current session ID",            "Display the active session identifier", None),
        ("sessions", "List all sessions",                  "Show every saved session", None),
        ("status",   "Show provider/model/session info",   "Display current configuration summary", None),
        ("think",    "Toggle thinking display",            "Show or hide thinking traces", None),
        ("retry",    "Resend the last message",            "Re-send your previous input to the agent", None),
        ("cancel",   "Cancel streaming response",          "Stop the current agent response", None),
        ("provider", "Manage providers (add|set|rm)", "Add, update, or remove a provider's API key", ["provider"]),
        ("model",    "Switch model",                       "Change the active model for the current provider", ["model"]),
        ("rename",   "Rename the current session",         "Give the session a new title", None),
        ("resume",   "Show last 5 turns of current session","Display recent conversation history", None),
        ("compact",  "Force memory compaction",            "Compress session context", None),
        ("health",   "Show service health",                "Display system health status", None),
        ("crash",    "Simulate crash (debug)",             "For testing crash recovery", None),
        ("companion","Toggle companion mode",              "Switch companion personality", None),
    ]

    for name, desc, help_text, arg_type in core:
        _COMMAND_DEFS[name] = (desc, help_text, arg_type)
        _COMMAND_DEFS["/" + name] = (desc, help_text, arg_type)


def get_commands() -> dict[str, tuple[str, str, list[str] | None]]:
    _init_command_registry()
    return _COMMAND_DEFS


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
    except Exception:
        pass

    # Fallback: check provider configs directly for api_key
    try:
        active = []
        for name in _all_known:
            try:
                cfg = settings.get(f"provider.{name}")
                if cfg and isinstance(cfg, dict) and cfg.get("api_key"):
                    active.append(name)
            except Exception:
                pass
        if active:
            return active
    except Exception:
        pass

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
        for i, (value, desc) in enumerate(self.items):
            marker = "▸" if i == self.selected else " "
            style = _ACCENT if i == self.selected else _TEXT
            dim = _DIM
            if i == self.selected:
                lines.append(
                    f"[{_ACCENT} bold]{marker} {value}[/]  [{dim}]{desc}[/]"
                )
            else:
                lines.append(
                    f"  [{style}]{value}[/]  [{dim}]{desc}[/]"
                )
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
        self.selected = min(self.selected + 1, len(self.items) - 1)

    def select_prev(self) -> None:
        if not self.items:
            return
        self.selected = max(self.selected - 1, 0)

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

class AmalgamHeader(Widget):
    """Multi-line centered header à la jcode."""
    session_id = reactive("")
    provider   = reactive("")
    model      = reactive("")
    status     = reactive("")

    def compose(self) -> ComposeResult:
        yield Static("", id="header-text", markup=True)

    def _short_id(self) -> str:
        s = self.session_id
        return (s[:22] + "…") if len(s) > 22 else s

    def _render_content(self) -> str:
        sid = self._short_id()
        lines: list[str] = []

        badges: list[str] = []
        if self.status:
            badges.append(self.status)
        if badges:
            lines.append(f"[{_DIM}]{'⟨' + '·'.join(badges) + '⟩'}[/]")

        client_text = f"client: {sid} ◆" if sid else "Amalgam"
        lines.append(f"[{_DIM}]{client_text}[/]")

        if self.provider and self.model:
            lines.append(
                f"[{_DIM}]{self.provider} · [/]"
                f"[{_PINK} bold]{self.model}[/]"
                f"[{_DIM}]  · /model to switch[/]"
            )
        elif self.model:
            lines.append(f"[{_PINK} bold]{self.model}[/]")

        lines.append(f"[{_DIM}]built recently[/]")
        lines.append(f"[{_DIM}]/help · Ctrl+Q quit · Ctrl+N new · Ctrl+R retry[/]")

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

    CSS = f"""
    Screen {{
        background: {_BG};
    }}

    AmalgamHeader {{
        dock: top;
        height: auto;
        background: {_SURFACE};
        border-bottom: solid {_BORDER};
    }}

    #header-text {{
        width: 100%;
        text-align: center;
        padding: 1 2;
        height: auto;
    }}

    #chat-log {{
        height: 1fr;
        background: {_BG};
        border: none;
        padding: 1 2;
        overflow-y: scroll;
        scrollbar-gutter: stable;
        scrollbar-color: {_SURFACE2} auto;
    }}

    #dropdown-container {{
        dock: bottom;
        height: auto;
        max-height: 15;
        layer: overlay;
        width: 100%;
        background: transparent;
        margin-bottom: 1;
    }}

    InlineDropdown {{
        background: {_SURFACE};
        border: solid {_ACCENT};
        height: auto;
        padding: 0 1;
        margin: 0 2;
        display: none;
    }}

    #dropdown-text {{
        padding: 0 1;
        height: auto;
    }}

    #input-container {{
        dock: bottom;
        height: auto;
        min-height: 1;
        background: {_SURFACE};
        padding: 0 1;
        border-top: solid {_BORDER};
    }}

    #input-area {{
        height: auto;
        min-height: 1;
        padding: 0;
    }}

    #chat-input {{
        background: {_SURFACE};
        color: {_TEXT};
        border: none;
        padding: 0 1;
        min-height: 1;
    }}

    #chat-input:focus {{
        border: none;
    }}

    #status-bar {{
        dock: bottom;
        height: 1;
        background: {_SURFACE};
        color: {_DIM};
        padding: 0 2;
        border-top: solid {_BORDER};
    }}

    #loading-overlay {{
        dock: top;
        height: 5;
        background: {_BG};
        align: center middle;
    }}

    #loading-text {{
        color: {_DIM};
        text-style: italic;
    }}

    #stream-area {{
        height: auto;
        max-height: 12;
        background: {_BG};
        color: {_GREEN};
        padding: 0 2;
        border: none;
    }}
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+n", "new_session", "New", priority=True),
        Binding("ctrl+l", "clear_screen", "Clear", priority=True),
        Binding("ctrl+r", "retry", "Retry", priority=True),
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
        if self._backend_loading:
            self._show_loading("Initializing backend…")
            self.query_one("#chat-input", Input).disabled = True
            self._update_status("Initializing…")
        else:
            self._update_header()
            self._log_system(f"Welcome — {self._short_id()}")
            self.query_one("#chat-input", Input).focus()

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
        self._update_status("Ctrl+Q quit · Ctrl+N new · Ctrl+R retry · /help")

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
            inp.value = f"/provider {value} "
        elif self._dropdown_mode == "model":
            self._skip_change = True
            inp.value = f"/model {value} "

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
            self._update_status("Ctrl+Q quit · Ctrl+N new · Ctrl+R retry · /help")
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
                        from cli.provider import KNOWN_PROVIDERS
                        items = [(p, "") for p in KNOWN_PROVIDERS]
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
                    from cli.provider import KNOWN_PROVIDERS
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
                # Show models from ALL configured providers
                detected = get_detected_providers(self._settings)
                all_models: list[str] = []
                for p_name in detected:
                    for m in get_models_for_provider(self._settings, p_name):
                        if m not in all_models:
                            all_models.append(m)
                items = [(m, "") for m in all_models]

                # If exact model name already typed, hide dropdown so Enter executes
                model_prefix = after_first.strip()
                if model_prefix:
                    exact = [v for v, _ in items if v == model_prefix.strip()]
                    if exact and not raw.endswith(" "):
                        self._hide_dropdown()
                        return

                self._show_dropdown("model", items, after_first.strip())

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
                except Exception:
                    pass
            self._update_header()
            self._log_system("New session" if cmd == "/new" else "Cleared")

        elif cmd == "/help":
            self._show_help()

        elif cmd == "/session":
            self._log_system(f"Session: {self._sid()}")

        elif cmd == "/sessions":
            self._list_sessions()

        elif cmd == "/status":
            self._show_status()

        elif cmd == "/think":
            self._show_thinking = not self._show_thinking
            self._log_system(f"Thinking: {'ON' if self._show_thinking else 'OFF'}")

        elif cmd == "/retry":
            if self._last_message:
                self._log_user(self._last_message)
                self._clear_stream_area()
                self._send_message(self._last_message)
            else:
                self._log_system("No previous message")

        elif cmd == "/cancel":
            self._cancel_stream()

        elif cmd == "/provider":
            parts = text.split(maxsplit=2)
            if len(parts) >= 2:
                subcmd = parts[1].lower()
                if subcmd in ("add", "set", "rm"):
                    if len(parts) >= 3:
                        self._handle_provider_key(subcmd, parts[2].lower())
                    else:
                        self._log_system(f"Usage: /provider {subcmd} <name>")
                else:
                    # Legacy: just switch active provider
                    self._set_provider(subcmd)
            # else: dropdown handles it via on_input_changed

        elif cmd == "/model":
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                self._set_model(parts[1])
            # else: dropdown handles it via on_input_changed

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
                    self._memory.compact()
                    self._log_system("Memory compacted")
            except Exception as e:
                self._log_error(f"Compaction failed: {e}")

        elif cmd == "/health":
            self._show_status()

        elif cmd == "/crash":
            self._log_error("Simulated crash for testing")
            try:
                import os, json, time
                crash_dir = os.path.join(os.path.expanduser("~"), ".amalgam")
                os.makedirs(crash_dir, exist_ok=True)
                with open(os.path.join(crash_dir, "crash_state.json"), "w") as f:
                    json.dump({
                        "session_id": self._sid(),
                        "provider": self._prov(),
                        "model": self._model(),
                        "last_message": "",
                        "timestamp": time.time(),
                    }, f)
            except Exception:
                pass
            self.exit(1)

        elif cmd == "/companion":
            self._log_system("Companion mode toggled")

        else:
            from cli.__init__ import _fuzzy_command_suggestion
            sug = _fuzzy_command_suggestion(text)
            if sug:
                self._log_error(f"Unknown: {text} — try {sug}?")
            elif text.startswith("/"):
                self._log_error(f"Unknown command: {text}")

    def _set_provider(self, name: str) -> None:
        from cli.provider import KNOWN_PROVIDERS
        if name not in KNOWN_PROVIDERS:
            fuzzy = [p for p in KNOWN_PROVIDERS if p.startswith(name.lower())]
            hint = f" — try {fuzzy[0]}?" if fuzzy else ""
            self._log_error(f"Unknown provider: {name}{hint}")
            return
        if self._settings:
            try:
                self._settings.set("provider.active", name)
                if self._llm:
                    self._llm.reload_settings()
                self._update_header()
                self._log_system(f"Provider → {name}")
            except Exception as e:
                self._log_error(f"Cannot set provider: {e}")

    def _handle_provider_key(self, action: str, name: str) -> None:
        """Handle /provider add|set|rm <name>."""
        from cli.provider import KNOWN_PROVIDERS
        if name not in KNOWN_PROVIDERS:
            fuzzy = [p for p in KNOWN_PROVIDERS if p.startswith(name)]
            hint = f" — try {fuzzy[0]}?" if fuzzy else ""
            self._log_error(f"Unknown provider: {name}{hint}")
            return

        if action == "rm":
            # Remove the API key from settings
            if self._settings:
                try:
                    cfg = self._settings.get(f"provider.{name}")
                    if isinstance(cfg, dict) and cfg.get("api_key"):
                        del cfg["api_key"]
                        self._log_system(f"API key removed for {name}")
                    else:
                        self._log_system(f"No API key found for {name}")
                except Exception as e:
                    self._log_error(f"Failed to remove key: {e}")
        else:  # add, set
            # Set up interactive API key prompt
            self._pending_api_key_for = (action, name)
            inp = self.query_one("#chat-input", Input)
            inp.password = True
            inp.placeholder = f"Enter API key for {name}:"
            inp.clear()
            self._update_status(f"Type API key for {name} and press Enter")

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
        self._update_status("Ctrl+Q quit · Ctrl+N new · Ctrl+R retry")

    def _show_status(self) -> None:
        tbl = Table(box=box.SIMPLE, show_header=False, style=_DIM)
        tbl.add_column("", style=_CYAN)
        tbl.add_column("", style=_TEXT)
        tbl.add_row("Provider", self._prov() or "?")
        tbl.add_row("Model", self._model() or "?")
        tbl.add_row("Session", self._sid())
        self._log_chat(tbl)

    def _list_sessions(self) -> None:
        try:
            if not self._memory:
                self._log_system("No memory backend")
                return
            current = self._memory.get_current_session()
            all_s = self._memory.get_sessions()
            if not all_s:
                self._log_system("No sessions found")
                return
            tbl = Table(box=box.SIMPLE, show_header=True, style=_DIM,
                        header_style=Style(color=_ACCENT))
            tbl.add_column("", style=_DIM, width=10)
            tbl.add_column("ID", style=_CYAN, no_wrap=True)
            tbl.add_column("Title", style=_TEXT)
            tbl.add_column("Msgs", justify="right", style=_GREEN)
            for s in all_s:
                sid = s.get("id", "?")
                mark = "▶ current" if sid == current else ""
                short = (sid[:22] + "…") if len(sid) > 22 else sid
                tbl.add_row(mark, short, s.get("title", "") or "",
                            str(s.get("message_count", 0)))
            self._log_chat(tbl)
        except Exception as e:
            self._log_error(f"Error listing sessions: {e}")

    # ── Agent streaming ─────────────────────────────────────────────────

    @textual_work(thread=False, exit_on_error=False)
    async def _send_message(self, text: str) -> None:
        if not self._agent:
            self._log_error("Agent not available")
            return

        self._streaming = True
        self._stream_task = asyncio.current_task()
        self._update_status("Streaming… (Esc to cancel)")

        try:
            stream: AsyncIterator = self._agent.handle_user_input(text)
            async for chunk in stream:
                if isinstance(chunk, tuple):
                    tag, val = chunk
                    self._handle_tag(tag, val)
                elif isinstance(chunk, str) and chunk.strip():
                    self._log_stream_chunk(chunk)
        except asyncio.CancelledError:
            self._log_system("Canceled")
        except Exception as e:
            self._log_error(str(e))
        finally:
            self._streaming = False
            self._stream_task = None
            self._update_status("Ctrl+Q quit · Ctrl+N new · Ctrl+R retry · /help")
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

    def _cancel_stream(self) -> None:
        self._streaming = False
        if self._stream_task is not None:
            self._stream_task.cancel()
            self._stream_task = None

    # ── Actions ─────────────────────────────────────────────────────────

    def action_new_session(self) -> None: self._handle_command("/new")
    def action_clear_screen(self) -> None: self._handle_command("/clear")
    def action_retry(self) -> None: self._handle_command("/retry")

    def action_cancel(self) -> None:
        if self._streaming:
            self._cancel_stream()
