"""
companion/relay.py — WebSocket relay server for TUI companion mode.

When the TUI enables companion mode, it starts this relay on a random port.
The overlay (PySide6 window) connects to it. Messages flow between the
overlay and the TUI's companion engine / LLM / TTS pipeline.

Protocol (JSON messages):
  Overlay → Relay:
    {type:"chat", text:"..."}           User said something (from STT or typed)
    {type:"stt_result", text:"...", confidence:0.9}  Speech recognition result
    {type:"idle_enter"}                 User went idle
    {type:"idle_exit"}                  User returned
    {type:"idle_timeout"}               User idle too long
    {type:"mute", muted:true/false}     Mute toggle
    {type:"ready"}                      Overlay loaded and VRM ready

  Relay → Overlay:
    {type:"expression", expression:"happy", intensity:0.8}
    {type:"tts_state", playing:true}
    {type:"voice_level", level:0.5}
    {type:"companion", content:"Hi!", context:"proactive"}
    {type:"settings_update", settings:{companion:{enabled:true}}}
"""

import asyncio
import json
import logging
from typing import Any, Callable, Optional, Set

import websockets
from websockets.server import WebSocketServerProtocol

logger = logging.getLogger(__name__)

MessageHandler = Callable[[dict[str, Any]], None]


class CompanionRelay:
    """WebSocket server that bridges overlay ↔ TUI companion engine.

    Uses the ``websockets`` library for proper RFC 6455 support.

    Usage:
        relay = CompanionRelay()
        port = await relay.start(on_overlay_message)
        subprocess.Popen([sys.executable, "-m", "companion.launcher",
                          "--ws-port", str(port)])
        ...
        relay.broadcast({"type": "expression", "expression": "happy"})
        ...
        await relay.stop()
    """

    def __init__(self) -> None:
        self._server: Optional[websockets.WebSocketServer] = None
        self._port: int = 0
        self._connections: Set[WebSocketServerProtocol] = set()
        self._on_message: Optional[MessageHandler] = None

    @property
    def port(self) -> int:
        return self._port

    async def start(self, on_message: Optional[MessageHandler] = None) -> int:
        """Start WebSocket server on a random port. Returns the port number."""
        self._on_message = on_message
        self._server = await websockets.serve(
            self._handle_connection, "127.0.0.1", 0,
            ping_interval=20, ping_timeout=10,
        )
        self._port = self._server.sockets[0].getsockname()[1]
        logger.info("Companion relay listening on ws://127.0.0.1:%d", self._port)
        return self._port

    async def stop(self) -> None:
        """Stop the relay server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._connections.clear()
        logger.info("Companion relay stopped")

    async def broadcast(self, msg: dict[str, Any]) -> None:
        """Send a JSON message to every connected overlay."""
        payload = json.dumps(msg)
        dead: Set[WebSocketServerProtocol] = set()
        for ws in self._connections:
            try:
                await ws.send(payload)
            except Exception:
                dead.add(ws)
        self._connections -= dead

    # ── Internal ──────────────────────────────────────────────────────────

    async def _handle_connection(self, ws: WebSocketServerProtocol) -> None:
        self._connections.add(ws)
        logger.debug("Overlay connected: %s", ws.remote_address)
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if self._on_message:
                    self._on_message(msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._connections.discard(ws)
            logger.debug("Overlay disconnected: %s", ws.remote_address)
