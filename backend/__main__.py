"""
Amalgam CLI — usage: python -m backend <command>

Commands:
  stats [--days N]    Show cost/usage statistics for the last N days (default: 7)
  curate              Run skill curator manually (grades, archives, merges skills)
  server              Start the FastAPI server (default if no command given)
  health              Print live service status (repeating every 5 s)
  setup               Run interactive setup wizard
  --check             Run pre-flight diagnostics once
  --version           Show version
"""

VERSION = "0.1.0"

import sys
import asyncio
import argparse


def main():
    parser = argparse.ArgumentParser(
        prog="python -m backend",
        description="Amalgam CLI \u2014 Backend entry point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Slash commands (in chat):
  /help     Show this help message
  /health   Show service health status
  /status   Show connection and system status
  /clear    Clear the chat display
  /settings Show current settings

Examples:
  python -m backend              Start in chat mode
  python -m backend --check      Run diagnostics
  python -m backend --check --verbose  Run diagnostics with details
  python -m backend health       Show health report
  python -m backend setup        Run setup wizard
  python -m backend --completions  Print shell completion hints
""",
    )
    parser.add_argument(
        "--version", action="store_true", help="Show version"
    )
    parser.add_argument(
        "--check", action="store_true", help="Run pre-flight diagnostics"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show detailed diagnostic output"
    )
    parser.add_argument(
        "--completions", action="store_true", help="Print shell completion hints"
    )

    subparsers = parser.add_subparsers(dest="command")

    sp = subparsers.add_parser("stats", help="Show cost/usage statistics")
    sp.add_argument("--days", type=int, default=7, help="Number of days to report (default: 7)")

    subparsers.add_parser("curate", help="Run skill curator manually")
    sp = subparsers.add_parser("server", help="Start the FastAPI server")
    sp.add_argument("--no-launch", "--no-browser", action="store_true",
                     help="Don't auto-open browser on server start")
    sp = subparsers.add_parser("health", help="Print live service status (repeating)")
    subparsers.add_parser("setup", help="Run interactive setup wizard")

    args = parser.parse_args()

    if args.version:
        _print_version()
        sys.exit(0)

    if args.completions:
        print_completion_hints()
        sys.exit(0)

    if args.check:
        asyncio.run(_run_check(verbose=args.verbose))
        sys.exit(0)

    # Dispatch subcommands
    if args.command == "stats":
        from backend.cli_stats import main as stats_main
        asyncio.run(stats_main(days=args.days))
        sys.exit(0)

    if args.command == "curate":
        asyncio.run(_run_curator())
        sys.exit(0)

    if args.command == "health":
        asyncio.run(_run_health_loop())
        sys.exit(0)

    if args.command == "setup":
        asyncio.run(_run_setup_wizard())
        sys.exit(0)

    # Default: run server (also when command is "server" or no command at all)
    import uvicorn

    if getattr(args, 'no_launch', False) or getattr(args, 'no_browser', False):
        os.environ["NO_BROWSER"] = "1"

    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="warning",
        ws_ping_interval=25,
        ws_ping_timeout=10,
    )


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

def _print_version():
    print(f"Amalgam version {VERSION}")


def print_completion_hints():
    """Print shell completion hints for bash/zsh."""
    print("""
# Bash completion for amalgam
_amalgam_completions() {
    local cur=${COMP_WORDS[COMP_CWORD]}
    local cmds="--help --version --check --verbose --completions api health setup curate stats"
    COMPREPLY=($(compgen -W "$cmds" -- "$cur"))
}
complete -F _amalgam_completions python -m backend
""")


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

class Style:
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

class Fg:
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    GRAY = '\033[90m'

def color(text: str, fg: str = None, style: str = None) -> str:
    """Apply ANSI colour codes, auto-reset. No-op if not a TTY."""
    if not sys.stdout.isatty():
        return text
    prefix = ''
    if fg: prefix += fg
    if style: prefix += style
    return f'{prefix}{text}{Style.RESET}' if prefix else text

def ok(text: str) -> str:
    return color(f'\u2713 {text}', Fg.GREEN)

def fail(text: str) -> str:
    return color(f'\u2717 {text}', Fg.RED)

def warn(text: str) -> str:
    return color(f'\u26A0 {text}', Fg.YELLOW)

def info(text: str) -> str:
    return color(text, Fg.CYAN)

def dim(text: str) -> str:
    return color(text, style=Style.DIM)

def bold(text: str) -> str:
    return color(text, style=Style.BOLD)


# Backward-compat aliases for existing callers
C_CYAN = Fg.CYAN
C_GREEN = Fg.GREEN
C_YELLOW = Fg.YELLOW
C_RED = Fg.RED
C_RESET = Style.RESET

def _c(text: str, fg: str = None) -> str:
    """Wrap *text* in ANSI colour (legacy)."""
    return color(text, fg=fg)


# ---------------------------------------------------------------------------
# --check / health
# ---------------------------------------------------------------------------

async def _run_check(verbose=False):
    """Run pre-flight diagnostics once and exit."""
    print()
    print(bold("=== Service Diagnostics ==="))
    print()
    all_ok = await _check_all_services(verbose=verbose)
    sys.exit(0 if all_ok else 1)


async def _run_health_loop():
    """Live-updating health dashboard."""
    try:
        while True:
            print("\033[2J\033[H", end="")
            print()
            print(bold("  Service Health Report \u2014 Live"))
            print()

            await _check_all_services(verbose=False)

            print(dim("  Press Ctrl+C to stop"))
            print()

            await asyncio.sleep(5)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


async def _check_all_services(verbose=False) -> bool:
    """Run all service checks, print a diagnostic report, return True if all healthy."""
    from backend.core.deps import get_shared
    from backend.core.health import get_registry, register_builtin_checks

    shared = get_shared()
    settings = shared.get("settings")

    register_builtin_checks(
        settings_obj=settings,
        llm_obj=shared.get("llm"),
        tts_obj=shared.get("tts"),
    )

    registry = get_registry()
    results = await registry.check_all()

    all_ok = True
    for name, state in sorted(results.items()):
        status_val = state["status"]
        status_color_fn = {
            "ok": ok,
            "degraded": warn,
            "down": fail,
            "not_configured": dim,
            "unknown": dim,
        }.get(status_val, dim)

        status_str = status_color_fn(status_val)
        latency_str = (
            f' ({state["latency_ms"]:.0f}ms)' if state.get("latency_ms") else ""
        )
        print(f"  {name:15s} {status_str}{latency_str}")

        if verbose and state.get("detail"):
            print(f'    {"":15s} {dim(state["detail"])}')

        if status_val != "ok":
            all_ok = False
            if verbose and state.get("last_error"):
                print(f'    {"":15s} {fail(state["last_error"])}')

    print()

    ok_count = sum(1 for s in results.values() if s["status"] == "ok")
    total = len(results)
    if ok_count == total:
        print(ok(f"All {total} services healthy"))
    else:
        print(fail(f"{total - ok_count}/{total} services unhealthy"))

    return all_ok


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

async def _run_setup_wizard():
    """Interactive setup wizard in terminal mode."""
    print()
    print("\u2550" * 52)
    print("  Amalgam Setup Wizard")
    print("\u2550" * 52)
    print()

    # --- Step 1: choose provider -------------------------------------------
    providers = [
        ("gemini", "Google Gemini"),
        ("openai", "OpenAI / ChatGPT"),
        ("anthropic", "Anthropic Claude"),
        ("groq", "Groq"),
        ("ollama", "Ollama (local)"),
        ("openrouter", "OpenRouter"),
        ("deepseek", "DeepSeek"),
    ]

    print("Available providers:")
    for i, (_, name) in enumerate(providers, 1):
        print(f"  {i}. {name}")
    print()

    provider_key = None
    while provider_key is None:
        try:
            choice = input("Select provider [1-7]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(providers):
                provider_key, provider_name = providers[idx]
        except (ValueError, IndexError):
            pass
        if provider_key is None:
            print("Invalid choice. Try again.")

    print()
    print(f"Selected: {provider_name}")
    print()

    # --- Step 2: API key (skip for local-only providers) --------------------
    api_key = ""
    if provider_key != "ollama":
        api_key = input(f"Enter API key for {provider_name}: ").strip()
        if not api_key:
            print("API key is required. Aborting.")
            sys.exit(1)

    # --- Step 3: model ------------------------------------------------------
    default_models = {
        "gemini": "gemini-2.0-flash",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-sonnet-4-20250514",
        "groq": "llama-3.3-70b-versatile",
        "ollama": "",
        "openrouter": "meta-llama/llama-3.1-8b-instruct:free",
        "deepseek": "deepseek-chat",
    }
    default_model = default_models.get(provider_key, "")

    if default_model:
        model = input(f"Model [{default_model}]: ").strip() or default_model
    else:
        model = input("Model (optional): ").strip()

    # --- Save ---------------------------------------------------------------
    print()
    print("Saving configuration...")

    from backend.core.config.settings import Settings

    s = Settings()
    s.set("provider.active", provider_key)
    if api_key:
        s.set(f"provider.{provider_key}.api_key", api_key)
    if model:
        s.set(f"provider.{provider_key}.model", model)

    print(_c("Configuration saved successfully!", C_GREEN))
    print()

    # --- Step 4: test connection -------------------------------------------
    print("Testing connection...")
    from backend.core.deps import get_shared

    async def _check_llm(shared) -> tuple[bool, str]:
        """Test the LLM connection using the shared container."""
        llm = shared.get("llm")
        if llm is None:
            return False, "LLM not initialized"
        try:
            resp = await llm.complete("Respond with exactly: OK", max_tokens=10)
            if resp and "ok" in resp.lower():
                return True, resp.strip()
            return True, resp.strip() if resp else "connected"
        except Exception as e:
            return False, str(e)

    ok, detail = await _check_llm(get_shared())
    if ok:
        print(f"  {_c('\u2713', C_GREEN)} Connection successful: {detail}")
    else:
        print(f"  {_c('\u2717', C_RED)} Connection failed: {detail}")
        print("  You can retry with 'python -m backend --check'")
    print()

    # --- Step 5: pick character --------------------------------------------
    print("Available characters:")
    try:
        chars = s.get_characters()
        char_names = list(chars.keys())
        for i, name in enumerate(char_names, 1):
            print(f"  {i}. {name}")
        print()
        char_choice = input(f"Select character [1-{len(char_names)}]: ").strip()
        try:
            idx = int(char_choice) - 1
            if 0 <= idx < len(char_names):
                s.set("character.active", char_names[idx])
                print(f"Character set to: {char_names[idx]}")
        except (ValueError, IndexError):
            print("Invalid choice. Skipping character selection.")
    except Exception as e:
        print(f"Could not load characters: {e}")

    print()
    print("\u2550" * 52)
    print("  Setup complete! Run 'python -m backend' to start the server.")
    print("\u2550" * 52)
    print()


# ---------------------------------------------------------------------------
# curate
# ---------------------------------------------------------------------------

async def _run_curator():
    """Run the skill curator manually with a real LLM caller."""
    import logging

    logging.basicConfig(level=logging.INFO)

    from backend.core.skills.curator import SkillCurator
    from backend.core.metrics import get_collector

    collector = get_collector()

    async def _curator_llm(prompt: str, **kwargs) -> str:
        from backend.core.deps import get_shared

        shared = get_shared()
        llm = shared.get("llm")
        if llm:
            max_tokens = kwargs.get("max_tokens", 500)
            resp = await llm.complete(prompt, max_tokens=max_tokens)
            return resp
        return ""

    curator = SkillCurator(metrics_collector=collector, llm_caller=_curator_llm)
    await curator.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
