"""
Companion mode — terminal-based interactive session with avatar overlay support.
Usage: python -m backend.cli.companion
"""
import asyncio
import sys
import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


async def companion_loop(agent_getter):
    """Interactive REPL loop for companion mode."""
    print("\n" + "=" * 50)
    print("  Amalgam Companion Mode")
    print("  Type '/help' for commands, '/quit' to exit")
    print("=" * 50 + "\n")

    agent = agent_getter()
    if not agent:
        print("Error: No agent available. Check your provider configuration.")
        return

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd = user_input[1:].lower()
            if cmd in ("quit", "exit", "q"):
                print("Goodbye!")
                break
            elif cmd == "help":
                print("Commands: /quit, /help, /clear")
            elif cmd == "clear":
                print("\n" * 100)
            continue

        print("AI: ", end="", flush=True)
        try:
            async for chunk in agent.handle_user_input(user_input):
                if isinstance(chunk, str):
                    print(chunk, end="", flush=True)
                elif isinstance(chunk, tuple) and chunk[0] == "__thinking__":
                    print(f"\n[thinking: {chunk[1]}]\n", end="", flush=True)
            print()
        except Exception as e:
            print(f"\n[Error: {e}]")


def main():
    """Entry point for python -m backend.cli.companion"""
    from backend.core.agent.factory import create_agent
    from backend.core.config.settings import Settings

    settings = Settings()
    agent = create_agent(settings=settings)

    async def run():
        await companion_loop(lambda: agent)

    asyncio.run(run())


if __name__ == "__main__":
    main()
