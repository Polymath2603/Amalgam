import asyncio
import json
import os
import sys
import time
import threading
import logging
import re
from typing import Optional

import websockets
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn

from cli import _make_console, _show_banner

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SLASH_COMMANDS = {
    "/exit": "Quit the companion (use twice to force quit)",
    "/help": "Show this help message",
    "/status": "Show connection and session status",
    "/wake": "Wake the companion from sleep mode",
    "/sleep": "Put the companion to sleep",
    "/clear": "Clear the screen",
    "/version": "Show companion version info",
}


class CompanionState:
    SLEEPING = "sleeping"
    ACTIVE = "active"


class CompanionMode:
    def __init__(self):
        self.console = _make_console()
        self.state = CompanionState.SLEEPING
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.last_interaction_time = time.time()
        self.timeout_duration = 46.0
        self.session_id = None
        self.base_url = os.environ.get("AMALGAM_WS_URL", "ws://localhost:8000/ws/chat")
        self._stop_event = asyncio.Event()
        self.current_response = ""
        self.is_thinking = False
        self._connected = False
        self._stt_timeout = float(os.environ.get("AMALGAM_STT_TIMEOUT", "30"))

    async def connect(self):
        """Connect with retry and a spinner showing progress."""
        self.console.print("[dim]Connecting to backend WebSocket...[/dim]")
        retry_count = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            task = progress.add_task(
                description="[cyan]Connecting to backend...[/cyan]", total=None
            )

            while not self._stop_event.is_set():
                try:
                    self.ws = await websockets.connect(self.base_url)
                    self._connected = True
                    progress.update(
                        task,
                        description="[green]Connected to backend WebSocket[/green]",
                    )
                    logger.info("Connected to backend WebSocket")
                    break
                except Exception as e:
                    retry_count += 1
                    progress.update(
                        task,
                        description=f"[yellow]Retrying... ({retry_count}) {e}[/yellow]",
                    )
                    await asyncio.sleep(1)

        if self._connected:
            self.console.print("[green]Ready. Speak or type messages.[/green]")

    async def _send(self, data: dict):
        if self.ws:
            await self.ws.send(json.dumps(data))

    async def wake_up(self, reason="wake_word"):
        if self.state == CompanionState.SLEEPING:
            self.state = CompanionState.ACTIVE
            self.console.print(f"[bold yellow][System][/bold yellow] Waking up... ({reason})")
            await self._send({"type": "command", "command": "voice_input_on"})
            await self._send({"type": "command", "command": "avatar_wake"})

    async def sleep(self, reason="timeout"):
        if self.state == CompanionState.ACTIVE:
            self.state = CompanionState.SLEEPING
            self.console.print(f"[bold yellow][System][/bold yellow] Going to sleep... ({reason})")
            await self._send({"type": "command", "command": "avatar_sleep"})
            await self._send({"type": "command", "command": "voice_input_off"})

    def _show_slash_help(self):
        """Print available slash commands in a formatted table."""
        from rich.table import Table
        from rich import box

        tbl = Table(
            title="Companion Slash Commands",
            box=box.ROUNDED,
            header_style="bold cyan",
            title_style="bold yellow",
        )
        tbl.add_column("Command", style="cyan")
        tbl.add_column("Description")

        for cmd, desc in sorted(SLASH_COMMANDS.items()):
            tbl.add_row(cmd, desc)

        self.console.print(tbl)

    def _show_status(self):
        """Print current companion status."""
        from rich.table import Table
        from rich import box

        tbl = Table(box=box.SIMPLE, show_header=False)
        tbl.add_column("Key", style="cyan")
        tbl.add_column("Value")
        tbl.add_row("State", self.state)
        tbl.add_row("Connected", str(self._connected))
        tbl.add_row("Endpoint", self.base_url)
        self.console.print(tbl)

    async def _show_typing_indicator(self):
        """Show a typing indicator while waiting for a response."""
        dots = 0
        while self.is_thinking:
            indicator = "." * (dots % 4)
            self.console.print(
                f"\r[dim]Companion is thinking{indicator:<4}[/dim]",
                end="",
            )
            dots += 1
            await asyncio.sleep(0.5)
        # Clear the indicator
        self.console.print("\r" + " " * 30 + "\r", end="")

    async def _handle_user_input(self, text: str):
        """Handle a user text input in companion mode."""
        # Check for slash commands first
        if text.startswith("/"):
            cmd = text.strip().lower()
            if cmd == "/help":
                self._show_slash_help()
                return
            elif cmd == "/status":
                self._show_status()
                return
            elif cmd == "/wake":
                await self.wake_up("manual")
                return
            elif cmd == "/sleep":
                await self.sleep("manual")
                return
            elif cmd == "/clear":
                self.console.clear()
                return
            elif cmd == "/version":
                self.console.print("[cyan]Amalgam Companion v1.0[/cyan]")
                return
            elif cmd == "/exit":
                self.console.print("[yellow]Use /exit again or press Ctrl+C to quit.[/yellow]")
                return
            else:
                self.console.print(f"[red]Unknown command:[/red] {text}")
                self.console.print("Type [cyan]/help[/cyan] for available commands.")
                return

        # Send the message
        await self._send(
            {"type": "message", "text": text, "session_id": self.session_id}
        )

        # Show typing indicator in background
        self.is_thinking = True
        indicator_task = asyncio.create_task(self._show_typing_indicator())

        # Wait for response
        response = ""
        while not self._stop_event.is_set():
            try:
                msg = await asyncio.wait_for(self.ws.recv(), timeout=0.5)
                data = json.loads(msg)
                msg_type = data.get("type", "")

                if msg_type == "text" or msg_type == "response":
                    chunk = data.get("text", data.get("content", ""))
                    if chunk:
                        response += chunk

                elif msg_type == "thinking":
                    self.console.print(f"[dim][thinking] {data.get('text', '')}[/dim]")

                elif msg_type == "tool_call":
                    tool = data.get("tool", data.get("name", "?"))
                    args = data.get("args", data.get("arguments", ""))
                    self.console.print(
                        Panel(
                            f"[cyan]{tool}({json.dumps(args) if isinstance(args, dict) else args})[/cyan]",
                            title="[bold cyan]Tool[/bold cyan]",
                            border_style="cyan",
                        )
                    )

                elif msg_type == "error":
                    self.console.print(
                        Panel(
                            f"[red]{data.get('text', data.get('message', 'Unknown error'))}[/red]",
                            title="[bold red]Error[/bold red]",
                            border_style="red",
                        )
                    )

                elif msg_type == "done" or data.get("done"):
                    break

            except asyncio.TimeoutError:
                if not self.is_thinking:
                    break
                continue
            except websockets.exceptions.ConnectionClosed:
                self._connected = False
                self.console.print("[red]Connection lost.[/red]")
                break

        self.is_thinking = False
        indicator_task.cancel()

        if response:
            self.console.print(f"\n[bold green]Companion:[/bold green] {response}\n")

    async def listen_loop(self):
        """Main loop: wait for user input in companion mode."""
        while not self._stop_event.is_set():
            try:
                text = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("You: ").strip()
                )
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n[yellow]Use /exit to quit, or Ctrl+C again to force quit.[/yellow]")
                try:
                    text = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("Confirm quit? (y/N): ").strip()
                    )
                    if text.lower() in ("y", "yes", "/exit"):
                        break
                    continue
                except (EOFError, KeyboardInterrupt):
                    break

            if not text:
                continue

            await self._handle_user_input(text)

    async def run(self):
        """Run the companion mode."""
        self.console.clear()
        self.console.rule("[bold yellow]Amalgam Companion Mode[/bold yellow]")
        self.console.print("[dim]Type /help for commands[/dim]\n")
        await self.connect()

        if not self._connected:
            self.console.print("[red]Could not connect to backend. Exiting.[/red]")
            return

        try:
            await self.listen_loop()
        except KeyboardInterrupt:
            pass
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Clean shutdown."""
        self._stop_event.set()
        self.state = CompanionState.SLEEPING
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.console.print("\n[green]Companion mode ended.[/green]")


def run_companion():
    """Entry point to launch companion mode."""
    con = _make_console()

    try:
        companion = CompanionMode()
        asyncio.run(companion.run())
    except KeyboardInterrupt:
        con.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(0)
    except Exception as e:
        con.print(f"[red]Companion error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_companion()
