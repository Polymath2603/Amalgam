"""
OAuth / login flow for Amalgam CLI providers.

Supports:
- Login flow for OAuth-enabled providers
- Login status display (which providers have keys)
- Interactive provider API key entry
- Token refresh

Usage:
  python main.py cli login <provider>
  python main.py cli login-status
"""
import os

# ---------------------------------------------------------------------------
# Provider login guides / instructions
# ---------------------------------------------------------------------------

LOGIN_GUIDES = {
    "gemini": {
        "name": "Google Gemini",
        "url": "https://aistudio.google.com/app/apikey",
        "hint": "Create an API key at Google AI Studio (free tier available).",
        "env_var": "GEMINI_API_KEY",
        "alt_env_vars": ["GOOGLE_API_KEY"],
    },
    "openai": {
        "name": "OpenAI",
        "url": "https://platform.openai.com/api-keys",
        "hint": "Create an API key at OpenAI Platform. Requires billing setup.",
        "env_var": "OPENAI_API_KEY",
    },
    "anthropic": {
        "name": "Anthropic",
        "url": "https://console.anthropic.com/",
        "hint": "Create an API key at Anthropic Console.",
        "env_var": "ANTHROPIC_API_KEY",
    },
    "claude": {
        "name": "Claude (Anthropic)",
        "url": "https://console.anthropic.com/",
        "hint": "Create an API key at Anthropic Console.",
        "env_var": "ANTHROPIC_API_KEY",
    },
    "groq": {
        "name": "Groq",
        "url": "https://console.groq.com/keys",
        "hint": "Create an API key at Groq Console (free tier available).",
        "env_var": "GROQ_API_KEY",
    },
    "deepseek": {
        "name": "DeepSeek",
        "url": "https://platform.deepseek.com/api_keys",
        "hint": "Create an API key at DeepSeek Platform.",
        "env_var": "DEEPSEEK_API_KEY",
    },
    "mistral": {
        "name": "Mistral AI",
        "url": "https://console.mistral.ai/api-keys/",
        "hint": "Create an API key at Mistral Console (free tier available).",
        "env_var": "MISTRAL_API_KEY",
    },
    "openrouter": {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/keys",
        "hint": "Create an API key at OpenRouter (many free models).",
        "env_var": "OPENROUTER_API_KEY",
    },
    "siliconflow": {
        "name": "SiliconFlow",
        "url": "https://siliconflow.cn/apikeys",
        "hint": "Create an API key at SiliconFlow.",
        "env_var": "SILICONFLOW_API_KEY",
    },
    "zai": {
        "name": "Z.AI",
        "url": "https://z.ai/",
        "hint": "Create an API key at Z.AI.",
        "env_var": "ZAI_API_KEY",
    },
    "huggingface": {
        "name": "HuggingFace",
        "url": "https://huggingface.co/settings/tokens",
        "hint": "Create a token at HuggingFace settings.",
        "env_var": "HUGGINGFACE_API_KEY",
    },
}


def login_provider(settings, provider_name: str) -> bool:
    """Interactive login flow for a provider.

    Returns True if key was set successfully.
    """
    from cli.output import markup, human_status

    guide = LOGIN_GUIDES.get(provider_name)
    if not guide:
        markup(f"[red]Unknown provider:[/red] {provider_name}")
        markup(f"[dim]Supported: {', '.join(sorted(LOGIN_GUIDES.keys()))}[/dim]")
        return False

    # Check if already configured
    existing_key = ""
    try:
        existing_key = settings.get(f"provider.{provider_name}.api_key", "").strip()
    except Exception:
        pass

    # Check env vars
    env_var = guide.get("env_var", "")
    alt_envs = guide.get("alt_env_vars", [])
    all_envs = [env_var] + alt_envs if env_var else alt_envs

    env_key = ""
    for ev in all_envs:
        if ev in os.environ and os.environ[ev].strip():
            env_key = os.environ[ev].strip()
            break

    if existing_key:
        markup(f"[green]✓[/green] {guide['name']} already has an API key configured")
        if env_key:
            markup(f"  [dim](Also found in ${env_var})[/dim]" if env_var else "")
        from rich.prompt import Confirm
        if not Confirm.ask("Overwrite?"):
            return True

    # Print guide
    markup(f"\n[bold cyan]{guide['name']} Login[/bold cyan]")
    markup(f"  {guide['hint']}")
    markup(f"  [blue]{guide['url']}[/blue]")
    markup(f"  [dim]Environment variable: ${env_var}[/dim]" if env_var else "")

    if env_key and not existing_key:
        from rich.prompt import Confirm
        markup(f"\n[green]Found key in ${env_var}![/green]")
        if Confirm.ask("Use this key?"):
            settings.set(f"provider.{provider_name}.api_key", env_key)
            markup(f"[green]✓[/green] API key saved for {guide['name']}")
            return True

    # Interactive prompt
    from rich.prompt import Prompt
    key = Prompt.ask(
        f"\nPaste your {guide['name']} API key",
        password=True,
    )

    if not key.strip():
        markup("[red]No key entered. Aborted.[/red]")
        return False

    # Save to settings
    settings.set(f"provider.{provider_name}.api_key", key.strip())
    markup(f"[green]✓[/green] API key saved for {guide['name']}")
    return True


def login_status(settings) -> list[dict]:
    """Return login status for all known providers.

    Returns list of dicts: {name, display_name, has_key: bool, source: str, model: str}
    """
    from cli.provider import detect_providers, resolve_display_name

    providers = detect_providers(settings)
    result = []
    for p in providers:
        if p.name in LOGIN_GUIDES or p.has_api_key:
            result.append({
                "name": p.name,
                "display_name": resolve_display_name(p.name),
                "has_key": p.has_api_key,
                "source": p.source,
                "model": p.model,
            })
    return result


def show_login_table(settings) -> None:
    """Print a formatted table of login status."""
    from cli.output import table

    rows = []
    for info in login_status(settings):
        key_status = "[green]✓[/green]" if info["has_key"] else "[dim]✗[/dim]"
        src = {"config": "settings", "env": "env var", "default": ""}.get(info["source"], info["source"])
        rows.append((
            info["display_name"],
            key_status,
            src,
            info["model"] or "[dim]–[/dim]",
        ))

    table(
        rows,
        headers=["Provider", "Key", "Source", "Model"],
        caption="Configured providers",
    )
