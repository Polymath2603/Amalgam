"""
companion/launcher.py — Standalone companion overlay launcher

Creates a transparent, always-on-top, frameless window using PySide6
with QtWebEngine to render the VRM overlay.

Usage:
    python companion/launcher.py [--port 8000] [--host 127.0.0.1]

Requires:
    PySide6 (pip install PySide6)
    Backend running on the given host:port
"""

import os
import sys
import argparse
import json
import logging

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="[Companion] %(levelname)s: %(message)s")
log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Launch Amalgam companion overlay")
    parser.add_argument("--port", type=int, default=8000, help="Backend port")
    parser.add_argument("--host", default="127.0.0.1", help="Backend host")
    parser.add_argument("--no-transparent", action="store_true",
                        help="Disable transparent window (for debugging)")
    args = parser.parse_args()

    # Check backend
    backend_url = f"http://{args.host}:{args.port}"
    try:
        import urllib.request
        resp = urllib.request.urlopen(f"{backend_url}/health", timeout=3)
        health = json.loads(resp.read())
        log.info(f"Backend OK: {health.get('status', '?')}")
    except Exception as e:
        log.error(f"Cannot connect to backend at {backend_url}: {e}")
        log.error("Make sure the Amalgam backend is running (python main.py webui --no-browser)")
        sys.exit(1)

    # Import PySide6
    try:
        from PySide6.QtWidgets import QApplication, QMainWindow
        from PySide6.QtCore import Qt, QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtGui import QSurfaceFormat
    except ImportError:
        log.error("PySide6 not installed. Run: pip install PySide6")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("Amalgam Companion")

    # Configure OpenGL surface format for WebGL support
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 5)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setAlphaBufferSize(8)
    fmt.setSamples(4)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)

    # Create main window
    window = QMainWindow()
    window.setWindowTitle("Amalgam Companion")

    # Window flags for overlay behavior
    flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    if not args.no_transparent:
        flags |= Qt.WindowTransparentForInput  # click-through
    window.setWindowFlags(flags)

    # Translucent background
    if not args.no_transparent:
        window.setAttribute(Qt.WA_TranslucentBackground)
        window.setAttribute(Qt.WA_NoSystemBackground, True)
        window.setStyleSheet("background: transparent;")

    # Full-screen
    window.showFullScreen()

    # WebEngine view
    web = QWebEngineView(window)
    web.setAttribute(Qt.WA_TranslucentBackground, True)
    web.page().setBackgroundColor(Qt.transparent)

    # Enable WebGL and other features
    from PySide6.QtWebEngineCore import QWebEngineSettings
    settings = web.settings()
    settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)
    settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
    settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
    settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
    settings.setAttribute(QWebEngineSettings.PdfViewerEnabled, False)
    settings.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)

    # Load the overlay HTML
    overlay_path = os.path.join(PROJECT_ROOT, "companion", "overlay.html")
    overlay_url = QUrl.fromLocalFile(overlay_path)
    web.load(overlay_url)

    # Make web view fill the window
    window.setCentralWidget(web)

    # Handle window close properly
    def cleanup():
        web.stop()
        app.quit()

    app.aboutToQuit.connect(cleanup)

    log.info("Companion overlay launched")
    log.info("  Controls:  Mouse to show buttons, Esc to exit")
    log.info("  Shortcuts: M = toggle mute, Esc = close")
    log.info("  Click-through is ON — mouse passes through the avatar")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
