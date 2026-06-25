"""
companion/launcher.py — Standalone companion overlay launcher

Transparent, always-on-top, frameless window using PySide6 + QtWebEngine.

Requires:
    pip install PySide6
    Backend running (python main.py webui --no-browser)
"""

import os
import sys
import argparse
import json
import logging
import threading
import subprocess
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="[Companion] %(levelname)s: %(message)s")
log = logging.getLogger(__name__)


def _find_free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_local_server(port: int) -> threading.Thread:
    """HTTP server serving from project root — avoids CORS issues with file://"""
    import http.server
    import socketserver

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(PROJECT_ROOT), **kw)
        def log_message(self, fmt, *a):
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return t


def main():
    parser = argparse.ArgumentParser(description="Launch Amalgam companion overlay")
    parser.add_argument("--port", type=int, default=8000, help="Backend HTTP port (ignored if --ws-port given)")
    parser.add_argument("--host", default="127.0.0.1", help="Backend host")
    parser.add_argument("--ws-port", type=int, default=None,
                        help="WebSocket relay port (skip health check, connect directly)")
    args = parser.parse_args()

    ws_port = args.ws_port if args.ws_port else args.port

    if not args.ws_port:
        # ── Check backend (only when no relay port given) ──
        backend_url = f"http://{args.host}:{args.port}"
        try:
            resp = urllib.request.urlopen(f"{backend_url}/api/health", timeout=3)
            health = json.loads(resp.read())
            log.info(f"Backend OK: {health.get('status', '?')}")
        except Exception as e:
            log.error(f"Cannot connect to backend at {backend_url}: {e}")
            log.error("Run: python main.py webui --no-browser")
            sys.exit(1)
    else:
        log.info("WS relay port provided — skipping backend health check")

    # ── Check if compositor is running; start xcompmgr if not ──
    # X11 needs a compositor for WA_TranslucentBackground to work
    compositor_proc = None
    if os.environ.get("DISPLAY"):
        # Check via xprop atom and running processes
        compositor_active = False
        try:
            has_cm = subprocess.run(
                ["xprop", "-root", "_NET_WM_CM_S0"],
                capture_output=True, text=True, timeout=3
            )
            # xprop outputs 'not found' when no compositor registered
            if "not found" not in has_cm.stdout and has_cm.stdout.strip():
                compositor_active = True
        except Exception:
            pass

        if not compositor_active:
            # Also check for known compositor processes
            try:
                ps_out = subprocess.run(
                    ["ps", "-A", "-o", "comm="],
                    capture_output=True, text=True, timeout=3
                )
                for name in ("xcompmgr", "picom", "compton", "mutter", "gnome-shell", "kwin"):
                    if name in ps_out.stdout:
                        compositor_active = True
                        break
            except Exception:
                pass

        if not compositor_active:
            # Start xcompmgr
            try:
                log.info("No compositor detected, starting xcompmgr...")
                compositor_proc = subprocess.Popen(
                    ["xcompmgr", "-n"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                log.info("xcompmgr started (PID %d)", compositor_proc.pid)
            except FileNotFoundError:
                log.warning("xcompmgr not found — transparency may not work")
            except Exception as e:
                log.warning(f"Could not start compositor: {e}")
        else:
            log.info("Compositor detected — transparency should work")

    # ── Start local HTTP server ──
    local_port = _find_free_port()
    _start_local_server(local_port)

    # ── PySide6 imports ──
    try:
        from PySide6.QtWidgets import QApplication, QMainWindow
        from PySide6.QtCore import Qt, QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtGui import QSurfaceFormat
    except ImportError:
        log.error("PySide6 not installed. Run: pip install PySide6")
        sys.exit(1)

    # ── Qt WebEngine flags for rendering ──
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        "--ignore-gpu-blocklist "
        "--enable-webgl "
    )

    # ── Application ──
    app = QApplication(sys.argv)
    app.setApplicationName("Amalgam Companion")

    # OpenGL surface format
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 5)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setAlphaBufferSize(8)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)

    # ── Window ──
    window = QMainWindow()
    window.setWindowTitle("Amalgam Avatar")
    window.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)

    # Transparent background with ARGB visual
    # Requires xcompmgr for per-pixel alpha
    window.setAttribute(Qt.WA_TranslucentBackground)
    window.setAttribute(Qt.WA_NoSystemBackground, True)

    # Full screen, transparent — desktop shows through wherever canvas has alpha=0
    window.showFullScreen()

    # ── WebEngine View ──
    web = QWebEngineView(window)

    # CRITICAL: make the WebEngine page itself transparent
    # This allows canvas alpha=0 pixels to show through to the window
    web.page().setBackgroundColor(Qt.GlobalColor.transparent)

    # WebGL and rendering settings
    s = web.settings()
    s.setAttribute(QWebEngineSettings.WebGLEnabled, True)
    s.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
    s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
    s.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
    s.setAttribute(QWebEngineSettings.PdfViewerEnabled, False)
    s.setAttribute(QWebEngineSettings.ScreenCaptureEnabled, False)
    s.setAttribute(QWebEngineSettings.ShowScrollBars, False)

    # Load overlay via local HTTP server (NOT file://) — pass ws_port to JS
    overlay_url = f"http://127.0.0.1:{local_port}/companion/overlay.html?ws_port={ws_port}"
    web.load(QUrl(overlay_url))

    window.setCentralWidget(web)
    window.show()

    # ── Cleanup ──
    def cleanup():
        web.stop()
        if compositor_proc:
            try:
                compositor_proc.terminate()
                compositor_proc.wait(timeout=3)
                log.info("xcompmgr stopped")
            except Exception:
                compositor_proc.kill()
        app.quit()
    app.aboutToQuit.connect(cleanup)

    log.info("Companion avatar window launched — FULL SCREEN, transparent")
    log.info(f"  URL:      http://127.0.0.1:{local_port}/companion/overlay.html")
    log.info(f"  Backend:  {backend_url}")
    log.info("  Desktop visible through transparent areas · VRM bottom-right")
    log.info("  Esc to close · Move mouse for controls")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
