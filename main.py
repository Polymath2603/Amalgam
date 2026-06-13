"""
Amalgam launcher.

Usage:
  python main.py help
  python main.py desktop
  python main.py webui
  python main.py cli
  python main.py --grpc
  python main.py cli --grpc
"""
import os
import sys
import argparse

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_TOKEN"] = ""

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TAURI_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "desktop", "tauri"
)

LOG_LEVEL_MAP = {0: "ERROR", 1: "WARNING", 2: "INFO", 3: "DEBUG"}


def _verbosity_to_level(v: int) -> str:
    return LOG_LEVEL_MAP.get(v, "DEBUG")


def _kill_port(port):
    """Kill any process listening on the given port."""
    import subprocess

    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True
        )
        pids = [p for p in result.stdout.strip().split("\n") if p]
        if pids:
            for pid in pids:
                subprocess.run(["kill", "-9", pid], capture_output=True)
            return len(pids)
    except FileNotFoundError:
        try:
            subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True)
        except FileNotFoundError:
            pass
    return 0


def _print_help():
    """Print colored help text to stderr."""
    from rich.console import Console
    from rich.table import Table
    from rich import box

    con = Console(stderr=True)
    con.print()
    con.print("[bold yellow]Amalgam[/bold yellow] — voice-first AI companion", style="bold")
    con.print()
    con.print("Usage: [bold]python main.py [command] [options][/bold]")
    con.print()
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Item", style="cyan")
    table.add_column("Description")
    table.add_row("webui", "Launch web UI [dim](default)[/dim]")
    table.add_row("cli", "Launch interactive CLI")
    table.add_row("desktop", "Build and launch Tauri desktop app")
    table.add_row("help", "Show this help message")
    con.print(table)
    con.print()
    con.print("[bold]Options:[/bold]")
    opt_table = Table(box=box.SIMPLE, show_header=False)
    opt_table.add_column("Flag", style="green")
    opt_table.add_column("Description")
    opt_table.add_row("--grpc", "Run gRPC server (or connect via CLI)")
    opt_table.add_row("--grpc-host HOST", "gRPC bind host [dim](default: 0.0.0.0)[/dim]")
    opt_table.add_row("--grpc-port PORT", "gRPC bind port [dim](default: 50051)[/dim]")
    opt_table.add_row("-v", "Verbosity: -v WARNING, -vv INFO, -vvv DEBUG [dim](default: ERROR)[/dim]")
    opt_table.add_row("--log-level LEVEL", "Log level: ERROR|WARNING|INFO|DEBUG [dim](overrides -v)[/dim]")
    opt_table.add_row("--log-format FMT", "Output format: console|json [dim](default: console)[/dim]")
    opt_table.add_row("--port PORT", "Web UI port [dim](default: 8000)[/dim]")
    opt_table.add_row("--host HOST", "Web UI bind host [dim](default: 0.0.0.0)[/dim]")
    opt_table.add_row("--no-browser", "Don't auto-open browser on webui start")
    con.print(opt_table)
    con.print()


def _launch_desktop(args=None):
    import subprocess

    if not os.path.isdir(TAURI_DIR):
        _error(f"Tauri directory not found at {TAURI_DIR}")
        sys.exit(1)

    _info("Starting backend server...")
    backend_args = [sys.executable, __file__, "webui"]
    if args:
        if args.log_level:
            backend_args.extend(["--log-level", args.log_level])
        elif args.verbose > 0:
            v = "-" + "v" * args.verbose
            backend_args.append(v)
        if args.no_browser:
            backend_args.append("--no-browser")
    server = subprocess.Popen(
        backend_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    import time
    import urllib.request

    _info("Waiting for backend...", end="", flush=True)
    for _ in range(30):
        try:
            with urllib.request.urlopen("http://localhost:8000/", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(1)
    else:
        _error("\nBackend failed to start within 30 seconds")
        server.terminate()
        sys.exit(1)
    _ok(" ready")

    _info("Launching desktop app...")
    _warn("If CSS looks wrong, run: cargo build in desktop/tauri/ to pick up changes")
    env = {**os.environ, "AMALGAM_SKIP_BACKEND": "1"}
    try:
        subprocess.run(["cargo", "run"], cwd=TAURI_DIR, env=env)
    except KeyboardInterrupt:
        _info("\nShutting down...")
    finally:
        server.terminate()
        server.wait(timeout=5)
        _kill_port(8000)
        _info("Shut down.")


# ---------------------------------------------------------------------------
# Colored console helpers (write to stderr, not stdout)
# ---------------------------------------------------------------------------

_console_stderr = None


def _get_con():
    global _console_stderr
    if _console_stderr is None:
        from rich.console import Console
        _console_stderr = Console(stderr=True)
    return _console_stderr


def _info(msg, **kwargs):
    _get_con().print(f"[cyan]Info:[/cyan] {msg}", **kwargs)


def _ok(msg, **kwargs):
    _get_con().print(f"[green]OK:[/green] {msg}", **kwargs)


def _warn(msg, **kwargs):
    _get_con().print(f"[yellow]Warning:[/yellow] {msg}", **kwargs)


def _error(msg, **kwargs):
    _get_con().print(f"[red]Error:[/red] {msg}", **kwargs)


def main():
    parser = argparse.ArgumentParser(
        description="Amalgam — voice-first AI companion",
        add_help=False,  # We handle --help ourselves
    )
    parser.add_argument(
        "frontend",
        nargs="?",
        choices=["help", "webui", "cli", "desktop", "telegram"],
        help="Frontend to launch (webui is default)",
    )
    parser.add_argument("--grpc", action="store_true", help="Run gRPC server (or connect via CLI)")
    parser.add_argument("--grpc-host", default="0.0.0.0", help="gRPC bind host")
    parser.add_argument("--grpc-port", type=int, default=50051, help="gRPC bind port")
    parser.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="Verbosity: -v WARNING, -vv INFO, -vvv DEBUG (default: ERROR)",
    )
    parser.add_argument(
        "--log-level", default=None, choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (overrides -v)",
    )
    parser.add_argument(
        "--log-format", default=None, choices=["console", "json"],
        help="Log output format",
    )
    parser.add_argument("--port", type=int, default=None, help="Web UI port (default: 8000)")
    parser.add_argument("--host", default=None, help="Web UI bind host (default: 0.0.0.0)")
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Don't auto-open browser on webui start",
    )
    parser.add_argument("--help", action="store_true", help="Show this help message")

    args, _ = parser.parse_known_args()

    # Handle --help or help command
    if args.help or args.frontend == "help":
        _print_help()
        sys.exit(0)

    from backend.core.log_config import configure_logging

    log_level = args.log_level or _verbosity_to_level(args.verbose)
    logger = configure_logging(level=log_level, log_format=args.log_format)

    if args.grpc and args.frontend != "cli":
        import asyncio
        from backend.grpc.server import serve_grpc

        _info(f"Starting gRPC server on {args.grpc_host}:{args.grpc_port}...")
        try:
            asyncio.run(serve_grpc(args.grpc_host, args.grpc_port))
        except OSError as e:
            _error(f"Failed to start gRPC server: {e}")
            _info(f"Make sure port {args.grpc_port} is available or use --grpc-port to change it")
            sys.exit(1)
        except KeyboardInterrupt:
            _info("gRPC server stopped")
        return

    if args.frontend is None or args.frontend == "help":
        _print_help()
        return

    if args.frontend == "desktop":
        _launch_desktop(args)
    elif args.frontend == "telegram":
        import asyncio
        from backend.api.telegram import run_telegram

        _info("Starting Telegram bot...")
        try:
            asyncio.run(run_telegram())
        except KeyboardInterrupt:
            _info("Telegram bot stopped")
    elif args.frontend == "cli":
        from cli import main as cli_main

        cli_main()
    else:
        port = args.port or int(os.environ.get("AMALGAM_PORT", "8000"))
        host = args.host or os.environ.get("AMALGAM_HOST", "0.0.0.0")

        # Check if port is already in use and warn
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
            sock.close()
        except OSError:
            _warn(f"Port {port} is already in use. Attempting to free it...")
            killed = _kill_port(port)
            if killed:
                _info(f"Freed port {port} (killed {killed} process(es))")
            else:
                _warn(f"Could not free port {port}. Try a different port or stop the existing process.")

        _info(f"Starting Amalgam web UI...")
        urls = [
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
        ]
        local_ip = _get_local_ip()
        if local_ip:
            urls.append(f"http://{local_ip}:{port}")
        for url in urls:
            _info(f"Chat UI: {url}")

        # Auto-open browser if not disabled
        if not args.no_browser:
            import webbrowser
            try:
                webbrowser.open(f"http://localhost:{port}")
            except Exception:
                pass

        import uvicorn

        uvicorn_log = log_level.lower() if log_level != "ERROR" else "error"
        logger.info("Starting Amalgam web UI...")
        logger.info(f"Chat UI: http://localhost:{port}")
        try:
            uvicorn.run(
                "backend.app:app",
                host=host,
                port=port,
                log_level=uvicorn_log,
                reload=False,
            )
        except KeyboardInterrupt:
            _info("Web UI stopped")
            sys.exit(0)


def _get_local_ip():
    """Get the local network IP address, or None."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _info("Interrupted")
        sys.exit(0)
    except Exception as e:
        _error(f"Unexpected error: {e}")
        sys.exit(1)
