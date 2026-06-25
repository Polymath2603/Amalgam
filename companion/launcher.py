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
    parser.add_argument("--port", type=int, default=8000, help="Backend port")
    parser.add_argument("--host", default="127.0.0.1", help="Backend host")
    args = parser.parse_args()

    backend_url = f"http://{args.host}:{args.port}"

    # ── Check backend ──
    try:
        resp = urllib.request.urlopen(f"{backend_url}/api/health", timeout=3)
        health = json.loads(resp.read())
        log.info(f"Backend OK: {health.get('status', '?')}")
    except Exception as e:
        log.error(f"Cannot connect to backend at {backend_url}: {e}")
        log.error("Run: python main.py webui --no-browser")
        sys.exit(1)

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

    # Small window positioned bottom-right — no compositor needed
    window.setFixedSize(280, 420)
    # Move to bottom-right of screen
    screen = QApplication.primaryScreen()
    if screen:
        sg = screen.availableGeometry()
        x = sg.x() + sg.width() - 300  # 20px margin
        y = sg.y() + sg.height() - 440
        window.move(x, y)

    # ── WebEngine View ──
    web = QWebEngineView(window)
    web.setStyleSheet("background: #000; border: none;")

    # WebGL and rendering settings
    s = web.settings()
    s.setAttribute(QWebEngineSettings.WebGLEnabled, True)
    s.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
    s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
    s.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
    s.setAttribute(QWebEngineSettings.PdfViewerEnabled, False)
    s.setAttribute(QWebEngineSettings.ScreenCaptureEnabled, False)
    s.setAttribute(QWebEngineSettings.ShowScrollBars, False)

    # Load overlay via local HTTP server (NOT file://)
    web.load(QUrl(f"http://127.0.0.1:{local_port}/companion/overlay.html"))

    window.setCentralWidget(web)
    window.show()

    # ── Cleanup ──
    def cleanup():
        web.stop()
        app.quit()
    app.aboutToQuit.connect(cleanup)

    log.info("Companion avatar window launched")
    log.info(f"  URL:      http://127.0.0.1:{local_port}/companion/overlay.html")
    log.info(f"  Backend:  {backend_url}")
    log.info("  Window is 280x420, frameless, always-on-top, bottom-right")
    log.info("  Mouse over window to show controls · Esc to close")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
