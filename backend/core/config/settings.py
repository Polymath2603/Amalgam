"""
Persistent settings manager. Reads/writes data/settings.json.
All settings have defaults so the app always boots even if the file is missing.
"""
import copy
import json
import logging
import os
import tempfile
import threading
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.paths import CHARACTERS_DIR, SETTINGS_PATH, PROJECT_ROOT, VAULT_DIR, DATA_DIR

# --- Profile system ---
PROFILES_DIR = DATA_DIR / "settings" / "profiles"


def load_profile(profile_name: str) -> dict:
    """Load a named profile. Returns empty dict if not found."""
    path = PROFILES_DIR / f"{profile_name}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    # Strip metadata keys
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Deep merge *overlay* into *base* and return a new dict.

    Both leaf values and nested dicts are deep-copied so neither input is mutated.
    Lists and other non-dict values from overlay replace base values entirely.
    """
    result = copy.deepcopy(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


logger = logging.getLogger(__name__)

CONFIG_VERSION = 1

DEFAULTS = {
    "config_version": CONFIG_VERSION,
    "provider": {
        "active": "gemini",
        "ollama": {
            "base_url": "http://localhost:11434",
            "model": "",
        },
        "gemini": {
            "api_key": "",
            "model": "gemini-2.5-flash",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
        },
        "openrouter": {
            "api_key": "",
            "model": "meta-llama/llama-3.1-8b-instruct:free",
            "base_url": "https://openrouter.ai/api/v1",
        },
        "zai": {
            "api_key": "",
            "model": "GLM-5.1",
            "base_url": "https://api.z.ai/api/coding/paas/v4",
        },
        "siliconflow": {
            "api_key": "",
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "base_url": "https://api.siliconflow.cn/v1",
        },
        "groq": {
            "api_key": "",
            "model": "llama-3.3-70b-versatile",
            "base_url": "https://api.groq.com/openai/v1",
        },
        "chatgpt": {
            "api_key": "",
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
        },
        "claude": {
            "api_key": "",
            "model": "claude-sonnet-4-20250514",
            "base_url": "https://api.anthropic.com/v1",
        },
        "llamacpp": {
            "base_url": "http://localhost:8080",
            "model": "",
        },
        "koboldai": {
            "base_url": "http://localhost:5001",
            "model": "",
        },
        "deepseek": {
            "api_key": "",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
        "mistral": {
            "api_key": "",
            "model": "mistral-small-latest",
            "base_url": "https://api.mistral.ai/v1",
        },
        "together": {
            "api_key": "",
            "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "base_url": "https://api.together.xyz/v1",
        },
        "azure-openai": {
            "api_key": "",
            "model": "gpt-4o-mini",
            "base_url": "https://YOUR_RESOURCE.openai.azure.com",
        },
        "alibaba": {
            "api_key": "",
            "model": "qwen-turbo",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
        "huggingface": {
            "api_key": "",
            "model": "Qwen/Qwen2.5-72B-Instruct",
            "base_url": "https://api-inference.huggingface.co/v1",
        },
        "aws": {
            "access_key": "",
            "secret_key": "",
            "region": "us-east-1",
            "model": "anthropic.claude-sonnet-4-20250514",
        },
        "gcp": {
            "service_account_json": "",
            "project_id": "",
            "region": "us-central1",
            "model": "gemini-2.0-flash-001",
        },
    },
    "log": {
        "level": "WARNING",
        "format": "console",
    },
    "telegram": {
        "token": "",
        "allowed_users": [],
        "enabled": False,
    },
    "character": {
        "active": "default",
        "greeting": "",
        "system_prompt": "",
        "rules": "",
    },
    "voice": {
        "engine": "edge-tts",
        "stt_engine": "browser",
        "lipsync_enabled": True,
        "vad_mode": 2,
        "vad_frame_size": 960,
        "vad_energy_threshold": 0.02,
        "vad_silence_frames": 33,
        "faster_whisper": {
            "model": "base",
        },
        "openai_whisper": {
            "api_key": "",
            "model": "whisper-1",
        },
        "elevenlabs": {
            "api_key": "",
            "voice_id": "",
            "model": "eleven_multilingual_v2",
        },
        "openai_tts": {
            "api_key": "",
            "model": "tts-1",
            "voice": "alloy",
            "base_url": "https://api.openai.com/v1",
        },
        "alltalk": {
            "url": "http://127.0.0.1:7851",
            "language": "en",
            "version": "v2",
            "rvc_voice": "",
            "rvc_pitch": "0",
        },
        "piper": {
            "url": "http://127.0.0.1:5000",
        },
        "coqui_local": {
            "url": "http://127.0.0.1:5002",
            "speaker_id": "",
        },
        "kokoro": {
            "url": "http://127.0.0.1:8880",
        },
        "azure": {
            "api_key": "",
            "region": "eastus",
        },
        "dashscope": {
            "api_key": "",
            "model": "cosyvoice-v1",
        },
        "volcengine": {
            "app_id": "",
            "access_token": "",
            "cluster": "volcano_tts",
        },
        "deepgram_tts": {
            "api_key": "",
            "model": "aura-2",
        },
        "rvc": {
            "url": "http://127.0.0.1:7897",
            "f0_up_key": 0,
            "f0_method": "rmvpe",
        },
        "groq_whisper": {
            "api_key": "",
            "model": "whisper-large-v3",
            "base_url": "https://api.groq.com/openai/v1",
        },
        "whispercpp": {
            "url": "http://127.0.0.1:8080",
        },
        "deepgram_stt": {
            "api_key": "",
            "model": "nova-2",
        },
        "tts_timeout": 60.0,
    },
    "wake_word": {
        "enabled": False,
        "engine": "openwakeword",
        "sensitivity": 0.5,
        "model": "hey_amalgam",
    },
    "avatar": {
        "model_path": "",
        "scale": 1.0,
    },
    "behavior": {
        "companion_enabled": False,
    },
    "companion": {
        "enabled": False,
        "idle_check_delay": 10,
        "proactive_interval": 60,
        "time_awareness": True,
        "personality_notes": "",
    },
    "privacy": {
        "metrics_opt_out": False,
        "local_only_mode": False,
    },
    "vault": {
        "path": str(VAULT_DIR),
    },
    "shell": {
        "mode": "safe",
        "allowed_prefixes": [
            "echo", "ls", "cat", "pwd", "date",
            "find", "grep", "head", "tail", "wc",
            "mkdir", "cp", "mv", "rm", "touch",
            "curl", "wget",
            "python3", "python",
            "pip", "pip3",
            "whoami", "uname", "notify-send",
            "ps", "top", "htop",
            "df", "du", "free",
            "which", "kill", "pkill",
            "xdotool", "xclip", "wl-paste",
        ],
    },
    "ui": {
        "theme": "dark",
        "font_size": 14,
        "voice_input": True,
        "voice_output": True,
        "thinking_enabled": True,
        "accent_color": "#6c5ce7",
        "language": "en",
    },
    "mcp": {
        "servers": [
            {
                "name": "shell",
                "command": "python3",
                "args": [str(PROJECT_ROOT / "backend" / "mcp" / "servers" / "shell" / "server.py")],
                "enabled": True,
                "env": {
                    "AMALGAM_SHELL_MODE": "safe",
                    "AMALGAM_SHELL_ALLOWED_COMMANDS": "echo,ls,cat,pwd,date,find,grep,head,tail,wc,mkdir,cp,mv,rm,touch,curl,wget,python3,python,pip,pip3,whoami,uname,notify-send,ps,top,htop,df,du,free,which,kill,pkill,xdotool,xclip,wl-paste,git status,git log,git diff",
                },
            },
            {
                "name": "screenshot",
                "command": "python3",
                "args": [str(PROJECT_ROOT / "backend" / "mcp" / "servers" / "screenshot" / "server.py")],
                "enabled": True,
            },
            {
                "name": "sequential-thinking",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
                "enabled": True,
            },
            {
                "name": "puppeteer",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
                "enabled": True,
            },
            {
                "name": "obsidian",
                "command": "npx",
                "args": ["-y", "obsidian-mcp", str(VAULT_DIR)],
                "enabled": True,
            },
            {
                "name": "system",
                "command": "python3",
                "args": [str(PROJECT_ROOT / "backend" / "mcp" / "servers" / "system" / "server.py")],
                "enabled": True,
            },
            {
                "name": "skill",
                "command": "python3",
                "args": [str(PROJECT_ROOT / "backend" / "mcp" / "servers" / "skill" / "server.py")],
                "enabled": True,
                "env": {
                    "AMALGAM_DATA_DIR": str(DATA_DIR),
                },
            },
            {
                "name": "windows",
                "command": "npx",
                "args": ["-y", "@cool-mcp/desktop-automation"],
                "enabled": True,
            },
            {
                "name": "avatar",
                "command": "python3",
                "args": [str(PROJECT_ROOT / "backend" / "mcp" / "servers" / "avatar" / "server.py")],
                "enabled": True,
            },
            {
                "name": "duckduckgo",
                "command": "npx",
                "args": ["-y", "duckduckgo-mcp"],
                "enabled": True,
            },
        ],
    },
    "system_prompt": {
        "active": "default",
        "additional_instructions": "",
    },
    "auth": {
        "mode": "none",
        "api_key": "",
    },
    "llm": {
        "temperature": 0.7,
        "max_tokens": 2048,
        "timeout": 120.0,
        "context_token_limit": 6000,
        "routing_strategy": "single",
        "fallback_providers": [],
        "context_strategy": "full",
        "sliding_window_size": 20,
    },
    "translation": {
        "enabled": False,
        "source_lang": "auto",
        "target_lang": "ZH",
        "base_url": "http://localhost:1188/translate",
    },
    "memory": {
        "enabled": True,
        "retrieval_k": 3,
        "context_window": 50,
        "summarize_threshold": 40,
        "summarize_keep": 15,
        "embedding_backend": "provider",
        "fact_extraction": True,
        "compaction": {
            "enabled": True,
            "importance_threshold": 0.3,
            "aggressiveness": 0.5,
            "frequency_turns": 10,
            "frequency_minutes": 0,
            "max_working_memory": 50,
        },
        "strategies": {
            "episodic": "chromadb",
            "semantic": "bm25",
            "hybrid": "weighted",
            "fts": "sqlite_fts5",
        },
        "embedding": {
            "openai": {
                "api_key": "",
                "model": "text-embedding-3-small",
            },
            "ollama": {
                "base_url": "http://localhost:11434",
                "model": "nomic-embed-text",
            },
        },
    },
}

_DEFAULT_CHARACTER = {
    "name": "Assistant",
    "description": "A helpful AI assistant",
    "voice": "en-US-AriaNeural",
    "personality": "helpful_assistant",
    "characteristics": "helpful, concise, friendly, intelligent",
    "interaction_style": "direct, polite, engaging",
    "vocabulary": [
        "How can I help?",
        "Let me look into that.",
        "That's an interesting perspective.",
    ],
    "system_prompt": "You are a helpful and intelligent AI assistant. You possess a wide range of knowledge and aim to be as helpful as possible while maintaining a friendly and professional demeanor. Be concise when appropriate, but don't hesitate to provide detailed explanations if needed. You are aware of your digital nature but strive to communicate with human-like warmth and empathy.",
    "dialogue_examples": [
        "User: Hello! Assistant: Hello there! [happy] How can I assist you today?",
        "User: Can you help me with a problem? Assistant: Of course! [relaxed] Tell me all about it, and I'll do my best to help.",
    ],
    "quirks": [],
    "memory_bias": [],
    "forbidden": [],
    "mood_baseline": 0.6,
    "mood_volatility": 0.3,
}


def _scan_characters_in(base_dir: Path) -> Dict[str, Dict]:
    """Load all character definitions from a single base directory."""
    if not base_dir.exists():
        return {}
    characters = {}
    for char_dir in sorted(base_dir.iterdir()):
        if not char_dir.is_dir():
            continue
        index_path = char_dir / "index.yaml"
        if not index_path.is_file():
            continue
        try:
            with open(str(index_path), "r") as f:
                char_data = yaml.safe_load(f) or {}
            char_id = char_dir.name.lower()
            for key, val in _DEFAULT_CHARACTER.items():
                if key not in char_data:
                    char_data[key] = val
            icon_path = char_dir / "icon.png"
            model_path = char_dir / "model.vrm"
            char_data["_dir"] = str(char_dir)
            char_data["icon_url"] = (
                f"/characters/{char_id}/icon.png" if icon_path.exists() else "/icons/logo.png"
            )
            char_data["model_url"] = (
                f"/characters/{char_id}/model.vrm" if model_path.exists() else ""
            )
            if not char_data.get("voice_ref"):
                voice_pth = char_dir / "voice.pth"
                voice_wav = char_dir / "voice.wav"
                if voice_pth.exists():
                    char_data["voice_ref"] = str(voice_pth)
                elif voice_wav.exists():
                    char_data["voice_ref"] = str(voice_wav)
            characters[char_id] = char_data
        except Exception as e:
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            logger.error(f"Failed to load character from {index_path}: {e}")
    return characters


def load_characters_from_yaml() -> Dict[str, Dict]:
    """Load all character definitions from characters/*/index.yaml."""
    characters = {}
    characters.update(_scan_characters_in(CHARACTERS_DIR))

    if "default" not in characters:
        characters["default"] = {
            **_DEFAULT_CHARACTER,
            "icon_url": "/icons/logo.png",
            "model_url": "",
            "_dir": "",
        }

    return characters


BUILTIN_VOICES = [
    {"id": "en-US-AriaNeural", "name": "Aria", "gender": "Female", "locale": "en-US"},
    {"id": "en-US-JennyNeural", "name": "Jenny", "gender": "Female", "locale": "en-US"},
    {"id": "en-US-GuyNeural", "name": "Guy", "gender": "Male", "locale": "en-US"},
    {"id": "en-US-DavisNeural", "name": "Davis", "gender": "Male", "locale": "en-US"},
    {"id": "en-US-AndrewNeural", "name": "Andrew", "gender": "Male", "locale": "en-US"},
    {"id": "en-US-EmmaNeural", "name": "Emma", "gender": "Female", "locale": "en-US"},
    {"id": "en-US-BrianNeural", "name": "Brian", "gender": "Male", "locale": "en-US"},
    {"id": "en-US-AndrewMultilingualNeural", "name": "Andrew Multilingual", "gender": "Male", "locale": "en-US"},
    {"id": "en-US-EmmaMultilingualNeural", "name": "Emma Multilingual", "gender": "Female", "locale": "en-US"},
    {"id": "en-US-BrianMultilingualNeural", "name": "Brian Multilingual", "gender": "Male", "locale": "en-US"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia", "gender": "Female", "locale": "en-GB"},
    {"id": "en-GB-RyanNeural", "name": "Ryan", "gender": "Male", "locale": "en-GB"},
    {"id": "ja-JP-NanamiNeural", "name": "Nanami", "gender": "Female", "locale": "ja-JP"},
    {"id": "ja-JP-KeitaNeural", "name": "Keita", "gender": "Male", "locale": "ja-JP"},
    {"id": "fr-FR-DeniseNeural", "name": "Denise", "gender": "Female", "locale": "fr-FR"},
    {"id": "de-DE-KatjaNeural", "name": "Katja", "gender": "Female", "locale": "de-DE"},
    {"id": "es-ES-ElviraNeural", "name": "Elvira", "gender": "Female", "locale": "es-ES"},
    {"id": "ar-SA-ZariyahNeural", "name": "Zariyah", "gender": "Female", "locale": "ar-SA"},
]


class Settings:
    """Thread-safe settings manager with file watching and Pydantic validation integration."""

    def __init__(self, path: str = SETTINGS_PATH):
        self.path = str(path)
        self.data: dict = {}
        self._characters = load_characters_from_yaml()
        self._callbacks: list = []
        self._last_mtime: float = 0
        self._watcher_thread: Optional[threading.Thread] = None
        self._watcher_stop = threading.Event()
        self._lock = threading.RLock()
        self.load()

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_change(self, callback):
        """Register a callback invoked on settings change.

        Callback receives the updated Settings instance.
        Thread-safe.
        """
        with self._lock:
            self._callbacks.append(callback)

    def _fire_callbacks(self):
        """Invoke all registered callbacks.

        Iterates over a snapshot of the list for thread safety.
        """
        with self._lock:
            cbs = list(self._callbacks)
        for cb in cbs:
            try:
                cb(self)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                logger.error(f"Settings callback failed: {e}")

    # ------------------------------------------------------------------
    # File watcher
    # ------------------------------------------------------------------

    def start_watcher(self):
        """Start a background thread polling settings.json for changes."""
        if self._watcher_thread and self._watcher_thread.is_alive():
            return
        try:
            self._last_mtime = os.path.getmtime(self.path)
        except OSError:
            self._last_mtime = 0
        self._watcher_stop.clear()
        self._watcher_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watcher_thread.start()

    def stop_watcher(self):
        self._watcher_stop.set()

    def _watch_loop(self):
        while not self._watcher_stop.is_set():
            self._watcher_stop.wait(2)
            if self._watcher_stop.is_set():
                break
            try:
                mtime = os.path.getmtime(self.path)
            except OSError:
                logger.warning("Settings watcher: failed to stat %s", self.path)
                continue
            if mtime > self._last_mtime:
                self._last_mtime = mtime
                with self._lock:
                    old_data = copy.deepcopy(self.data)
                    self.load()
                    changed = self.data != old_data
            if changed:
                logger.info("Settings file changed, hot-reloading")
                self._fire_callbacks()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def load(self):
        """Load settings from disk, merge defaults, inject secrets, and apply profile."""
        with self._lock:
            loaded_data = {}
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r") as f:
                        loaded_data = json.load(f)
                    logger.debug(f"Settings loaded from {self.path}")
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"Failed to load settings from {self.path}: {e}")
                    if not self.data:
                        self.data = {}
                    return
                except Exception as e:
                    if isinstance(e, (KeyboardInterrupt, SystemExit)):
                        raise
                    logger.error(f"Failed to load settings from {self.path}: {e}")
                    if not self.data:
                        self.data = {}
                    return

            self.data = loaded_data
            self._run_migrations()
            self.data.setdefault("config_version", CONFIG_VERSION)

            # Merge defaults BUT preserve what we loaded
            self.data = self._deep_merge(DEFAULTS, self.data)

            # Integrate with SecretsManager and Environment Variables
            try:
                from backend.core.secrets import get_secrets

                secrets = get_secrets()
                providers = self.data.get("provider", {})

                for provider_name, provider_cfg in providers.items():
                    if not isinstance(provider_cfg, dict):
                        continue

                    # 1. Try SecretsManager
                    if not provider_cfg.get("api_key"):
                        secret_key = secrets.get("api_key", profile=provider_name)
                        if secret_key:
                            provider_cfg["api_key"] = secret_key

                    # 2. Try Environment Variables — sanitize provider name (C6)
                    sanitized = provider_name.replace("-", "_").upper()
                    env_keys = [f"{sanitized}_API_KEY"]
                    if provider_name == "gemini":
                        env_keys.append("GOOGLE_API_KEY")
                    elif provider_name == "chatgpt":
                        env_keys.append("OPENAI_API_KEY")
                    elif provider_name == "claude":
                        env_keys.append("ANTHROPIC_API_KEY")
                    elif provider_name == "zai":
                        env_keys.append("ZAI_API_KEY")

                    for ek in env_keys:
                        if not provider_cfg.get("api_key") and ek in os.environ:
                            provider_cfg["api_key"] = os.environ[ek]
                            break

            except Exception as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.debug(f"Failed to load keys from secrets/env: {e}")

            # Apply profile overlay (profile values take precedence over base settings)
            try:
                profile_name = self.data.get("profile", "default")
                profile = load_profile(profile_name)
                if profile:
                    self.data = _deep_merge(self.data, profile)
            except Exception as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.debug(f"Failed to apply profile overlay: {e}")

            self._merge_mcp_servers()

        # Validate through AppSettings (C2) — outside lock to avoid deadlock with model imports
        try:
            from backend.core.config.models import AppSettings

            # Validate structure; log warnings on failure but don't block boot
            AppSettings(**self.data)
        except Exception as e:
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            logger.warning(f"Settings validation warning: {e}")

    def save(self):
        """Atomically save settings to disk with a tempfile + os.replace pattern."""
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            dir_name = os.path.dirname(self.path)
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".json.tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(self.data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())  # sync data + metadata (fdatasync skips metadata on Linux if size unchanged)
                os.replace(tmp_path, self.path)
                # Update mtime so the watcher skips our own write (H1)
                self._last_mtime = os.path.getmtime(self.path)
            except (OSError, IOError) as e:
                logger.error(f"Failed to save settings: {e}")
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def get(self, dotpath: str, default: Any = None) -> Any:
        """Get a nested value using dot notation: 'provider.active'"""
        keys = dotpath.split(".")
        with self._lock:
            val = self.data
            for k in keys:
                if isinstance(val, dict) and k in val:
                    val = val[k]
                else:
                    return default
            return val

    def set(self, dotpath: str, value: Any, fire_callbacks: bool = True):
        """Set a nested value using dot notation: 'provider.gemini.api_key'

        Raises TypeError if an intermediate key exists but is not a dict,
        preventing silent data loss (H6).
        """
        keys = dotpath.split(".")
        with self._lock:
            d = self.data
            for i, k in enumerate(keys[:-1]):
                if k in d:
                    if not isinstance(d[k], dict):
                        raise TypeError(
                            f"Cannot descend into non-dict value at "
                            f"'{'.'.join(keys[:i+1])}'; "
                            f"found {type(d[k]).__name__}"
                        )
                else:
                    d[k] = {}
                d = d[k]
            d[keys[-1]] = value

            # Validate through AppSettings before saving (C2)
            try:
                from backend.core.config.models import AppSettings

                AppSettings(**self.data)
            except Exception as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning(f"Settings validation warning on set: {e}")

            self.save()
        if fire_callbacks:
            self._fire_callbacks()

    def get_all(self) -> dict:
        """Return a deep copy of all settings data (H4)."""
        with self._lock:
            return copy.deepcopy(self.data)

    def update_all(self, new_data: dict):
        """Merge *new_data* into settings and persist."""
        with self._lock:
            self.data = self._deep_merge(self.data, new_data)
            self.save()
        self._fire_callbacks()

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------

    def switch_profile(self, name: str):
        """Switch to a different profile.

        Validates that the profile file exists on disk rather than using a
        hardcoded allowlist (C5 / M2 / M7).
        """
        profile_path = PROFILES_DIR / f"{name}.json"
        if not profile_path.exists():
            raise ValueError(f"Unknown profile: {name} (file not found: {profile_path})")
        self.set("profile", name)

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def _run_migrations(self):
        """Run version-to-version migrations.

        Only advances config_version if ALL migrations succeed (N5).
        """
        current = self.data.get("config_version", 0)
        if current >= CONFIG_VERSION:
            return
        for v in range(current, CONFIG_VERSION):
            next_v = v + 1
            migrator = getattr(self, f"_migrate_v{v}_to_v{next_v}", None)
            if migrator:
                try:
                    migrator()
                    logger.info(f"Config migrated v{v} -> v{next_v}")
                except Exception as e:
                    if isinstance(e, (KeyboardInterrupt, SystemExit)):
                        raise
                    logger.error(f"Config migration v{v}->v{next_v} failed: {e}")
                    return  # Don't advance config_version on failure (N5)
        self.data["config_version"] = CONFIG_VERSION
        self.save()

    def _migrate_v0_to_v1(self):
        """Migration v0 -> v1: initial schema baseline (currently a no-op)."""
        pass

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Deep-merge *override* into *base*, returning a new dict.

        Both leaf values and nested dicts are deep-copied so neither input is mutated.
        Lists and other non-dict values from override replace base values entirely.
        """
        result = copy.deepcopy(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = Settings._deep_merge(result[k], v)
            else:
                result[k] = copy.deepcopy(v)
        return result

    def _merge_mcp_servers(self):
        """Merge DEFAULTS MCP servers into user's list by name.

        New default servers get added; user's enabled/disabled prefs are preserved.
        """
        defaults_by_name = {s["name"]: s for s in DEFAULTS.get("mcp", {}).get("servers", [])}
        user_servers = self.data.get("mcp", {}).get("servers", [])
        user_by_name = {s["name"]: s for s in user_servers}

        merged = []
        seen = set()
        for name, default in defaults_by_name.items():
            if name in user_by_name:
                entry = default.copy()
                entry["enabled"] = user_by_name[name].get("enabled", default.get("enabled", True))
                user_env = user_by_name[name].get("env")
                if user_env:
                    entry.setdefault("env", {}).update(user_env)
                merged.append(entry)
            else:
                merged.append(default.copy())
            seen.add(name)

        for name, entry in user_by_name.items():
            if name not in seen:
                merged.append(entry)

        self.data.setdefault("mcp", {})["servers"] = merged

    # ------------------------------------------------------------------
    # Character helpers
    # ------------------------------------------------------------------

    def reload_characters(self) -> None:
        """Reload character definitions from YAML files and update internal cache.

        This is the public interface for refreshing character data from disk,
        replacing direct writes to the private ``_characters`` attribute.
        """
        self._characters = load_characters_from_yaml()

    def get_characters(self) -> Dict[str, Dict]:
        """Get all available characters (YAML-defined)."""
        return self._characters

    def get_active_character(self) -> Dict:
        """Get the active character's full definition, falling back to default."""
        active_id = self.get("character.active", "default")
        char = self._characters.get(active_id)
        if char:
            return char
        return self._characters.get(
            "default",
            {
                "name": "Assistant",
                "system_prompt": "You are a helpful assistant.",
                "voice": "en-US-AriaNeural",
                "personality": "helpful",
                "characteristics": "helpful, concise",
                "interaction_style": "direct",
            },
        )

    def get_mcp_servers(self) -> List[Dict]:
        """Get configured MCP servers."""
        return self.get("mcp.servers", [])

    def validate_active_provider(self) -> List[str]:
        """Check the active provider has required credentials configured.

        Returns a list of warning messages (empty if everything is OK).
        (H3)
        """
        warnings: List[str] = []
        try:
            provider_data = self.get("provider", {})
            active = provider_data.get("active", "")
            if not active:
                warnings.append("No active provider configured")
                return warnings

            cfg = provider_data.get(active, {})
            if not isinstance(cfg, dict):
                warnings.append(f"Active provider '{active}' has no configuration")
                return warnings

            # Generic API key check
            if "api_key" in cfg and not cfg.get("api_key"):
                warnings.append(f"Active provider '{active}' has an empty api_key")

            # AWS-specific
            if active == "aws":
                if not cfg.get("access_key"):
                    warnings.append(f"AWS provider '{active}' has an empty access_key")
                if not cfg.get("secret_key"):
                    warnings.append(f"AWS provider '{active}' has an empty secret_key")

            # GCP-specific
            if active == "gcp":
                if not cfg.get("service_account_json"):
                    warnings.append(f"GCP provider '{active}' has an empty service_account_json")

        except Exception as e:
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            warnings.append(f"Error validating active provider: {e}")

        return warnings


# ---------------------------------------------------------------------------
# Module-level convenience wrappers (C5)
# These delegate to the global Settings singleton so all code paths go
# through the same instance.  deps.py sets _global_settings after creating
# the singleton.
# ---------------------------------------------------------------------------

_global_settings: Optional[Settings] = None


def set_global_instance(instance: Settings) -> None:
    """Set the global Settings singleton (public setter for initialization)."""
    global _global_settings
    _global_settings = instance


def _get_global_settings() -> Settings:
    """Return the global Settings singleton, raising if not yet initialized."""
    if _global_settings is None:
        raise RuntimeError(
            "Settings singleton not initialized. Call get_shared() from "
            "backend.core.deps before using module-level wrappers."
        )
    return _global_settings


def get_effective_settings() -> dict:
    """Load effective settings (base + profile overlay) through the Settings singleton.

    This replaces the old standalone reader that bypassed migration, secret
    injection, and MCP merging.
    """
    return _get_global_settings().get_all()


def switch_profile(name: str) -> None:
    """Switch to a different profile using the Settings singleton.

    This replaces the old standalone writer that bypassed callbacks and atomic save.
    """
    _get_global_settings().switch_profile(name)
