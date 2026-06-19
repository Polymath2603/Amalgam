"""
gRPC server daemon manager for the Amalgam CLI.

Handles:
- Starting a background gRPC server (daemon) for persistent agent sessions
- Stopping the daemon
- Checking status (alive / dead)
- Ensuring a server is running before connecting

Used by:  python main.py cli serve    # start daemon
          python main.py cli           # (auto) connect to running daemon
          python main.py cli stop      # stop daemon
          python main.py cli status    # check daemon status (runs from CLI mode)
"""
import asyncio
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

DAEMON_DIR = os.path.join(os.path.expanduser("~"), ".amalgam")
PID_FILE = os.path.join(DAEMON_DIR, "daemon.pid")
STATUS_FILE = os.path.join(DAEMON_DIR, "daemon.json")
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 50051


def _ensure_daemon_dir() -> None:
    """Create ~/.amalgam/ if it doesn't exist."""
    os.makedirs(DAEMON_DIR, exist_ok=True)


def _read_pid() -> int | None:
    """Read the PID file. Returns None if missing or invalid."""
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
            return pid
    except (FileNotFoundError, ValueError, OSError):
        return None


def _write_pid(pid: int) -> None:
    """Write PID to file."""
    _ensure_daemon_dir()
    with open(PID_FILE, "w") as f:
        f.write(str(pid))


def _clear_pid() -> None:
    """Remove PID file."""
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    try:
        os.remove(STATUS_FILE)
    except OSError:
        pass


def _is_running(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def status() -> dict:
    """Check server daemon status.

    Returns:
        dict with keys: running (bool), pid (int|None),
                        host (str), port (int), uptime (float|None)
    """
    pid = _read_pid()
    info: dict = {
        "running": False,
        "pid": pid,
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "uptime": None,
    }
    if pid and _is_running(pid):
        info["running"] = True
        try:
            with open(STATUS_FILE) as f:
                meta = json.load(f)
                info.update(meta)
        except Exception:
            pass
        try:
            now = time.time()
            proc_create = os.path.getctime(f"/proc/{pid}")
            info["uptime"] = now - proc_create
        except Exception:
            pass
        return info

    if pid and not _is_running(pid):
        _clear_pid()
        info["pid"] = None

    return info


def start(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          log_level: str = "ERROR", daemonize: bool = True) -> dict:
    """Start the gRPC server daemon.

    If daemonize=True (default), spawns a detached subprocess.
    If daemonize=False, runs in the foreground (blocking).

    Returns status dict after startup.
    """
    existing = status()
    if existing["running"]:
        return existing

    _ensure_daemon_dir()

    if not daemonize:
        from backend.grpc.server import serve_grpc
        try:
            asyncio.run(serve_grpc(host, port))
        except KeyboardInterrupt:
            pass
        return {"running": False, "pid": None}

    # Daemon mode: spawn detached subprocess
    python = sys.executable
    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"
    )
    cmd = [
        python, script, "cli", "serve",
        "--grpc-host", host,
        "--grpc-port", str(port),
        "--daemon",
        "--log-level", log_level,
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for the daemon process to write its PID
    for _ in range(30):
        time.sleep(0.2)
        st = status()
        if st["running"]:
            return st
        # Check if the subprocess crashed
        ret = proc.poll()
        if ret is not None and ret != 0:
            logger.error(f"Daemon process exited with code {ret}")
            break

    logger.error("Daemon failed to start within 6 seconds")
    return status()


def stop(timeout: float = 5.0) -> dict:
    """Stop the server daemon.

    Sends SIGTERM, waits for graceful shutdown, then SIGKILL if needed.

    Returns status dict after stop.
    """
    pid = _read_pid()
    if not pid:
        _clear_pid()
        return status()

    if not _is_running(pid):
        _clear_pid()
        return status()

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass

    waited = 0.0
    step = 0.2
    while waited < timeout:
        if not _is_running(pid):
            _clear_pid()
            return status()
        time.sleep(step)
        waited += step

    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass

    _clear_pid()
    return status()


def restart(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
            log_level: str = "ERROR") -> dict:
    """Restart the server daemon."""
    stop()
    time.sleep(0.5)
    return start(host, port, log_level)


def ensure(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
           log_level: str = "ERROR") -> dict:
    """Ensure a server is running. Start one if not already running.

    Returns status dict.
    """
    st = status()
    if st["running"]:
        return st
    if _probe_port(host, port):
        return {"running": True, "pid": None, "host": host, "port": port}
    return start(host, port, log_level)


def _probe_port(host: str, port: int) -> bool:
    """Probe if a gRPC server is listening on the given host:port."""
    try:
        import grpc
        import asyncio

        async def probe():
            try:
                async with grpc.aio.insecure_channel(
                    f"{host}:{port}",
                    options=(("grpc.timeout", 2000),),
                ) as chan:
                    try:
                        await asyncio.wait_for(chan.channel_ready(), timeout=1.0)
                        return True
                    except (grpc.aio.AioRpcError, asyncio.TimeoutError):
                        pass
                    # Fallback: TCP probe
                    return _tcp_probe(host, port)
            except Exception:
                return _tcp_probe(host, port)

        return asyncio.run(probe())
    except (AttributeError, Exception):
        return _tcp_probe(host, port)


def _tcp_probe(host: str, port: int) -> bool:
    """Simple TCP connect probe."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()
