# Config/Settings Layer — Aggressive Code Review

**Files reviewed:**
- `backend/core/config/settings.py` (775 lines) — Runtime settings manager
- `backend/core/config/models.py` (954 lines) — Pydantic typed models
- `backend/core/config/schema.py` (29 lines) — Stub schema (dead)
- `backend/core/startup.py` — Hot-reload integration
- `backend/core/paths.py` — Central path definitions
- `backend/core/secrets.py` — Secrets manager
- `backend/core/deps.py` — Singleton injection

**Review date:** 2026-06-22

---

## CRITICAL

### [C1] Thread safety: zero locks on settings data access
**File:** `settings.py:528–710`
**Severity:** CRITICAL

The `Settings` class has **no lock** protecting `self.data`. The watcher thread (running `_watch_loop`) calls `self.load()` which *replaces* `self.data`. Meanwhile `set()`, `update_all()`, and `get()` read/write `self.data` from the main thread. This is a textbook data race.

**Specific race scenario:**
1. `set("provider.active", "ollama")` navigates to `self.data["provider"]` and holds a reference to the `provider` sub-dict.
2. Watcher calls `load()` → `self.data = {new dict}`
3. `set()` writes to the *stale* sub-dict reference from step 1.
4. `save()` writes `self.data` (the new dict from step 2) — the change is **silently lost**.

**Fix:** Add a `threading.Lock` (or `RLock`) and guard every read/write of `self.data`. Acquire it in `load()`, `save()`, `set()`, `get()`, `update_all()`, `get_all()`, `_fire_callbacks()`, and `_merge_mcp_servers()`.

---

### [C2] models.py Pydantic models are completely unused — dead code
**File:** `models.py:1–954`
**Severity:** CRITICAL

`grep -r "from backend.core.config.models import"` returns zero results. Nobody in the entire codebase imports `AppSettings`, `LLMProviderConfig`, or any other model from `models.py`. All consumers use the raw dict-based `Settings` class from `settings.py`.

This means 954 lines of carefully typed Pydantic models with `SecretStr`, `Literal` constraints, range validators, and aliases are **ship without any effect**. Any bug in these models silently harms future adopters while providing zero value today.

**Fix:** Either (a) integrate `AppSettings` as the storage backend of the `Settings` class (validate-on-write), or (b) delete `models.py` to avoid confusion. Half measures are dangerous.

---

### [C3] `schema.py` declares a conflicting, obsolete `AppSettings`
**File:** `schema.py:1–29`
**Severity:** CRITICAL

There are **two** `AppSettings` Pydantic classes:
- `models.py:853` — full (17 sections, 954 lines)
- `schema.py:26` — minimal (3 sections, 29 lines)

They have different structures, different defaults, and incompatible validation. The `schema.py` version defaults `stt_engine` to `"faster-whisper"` while `settings.py:179` defaults it to `"browser"`. Its `embedding_backend` pattern (`^(provider|local|disabled)$`) rejects valid values `"openai"` and `"ollama"` used elsewhere.

`schema.py` appears to be a stale early draft. Its presence makes it impossible to know which `AppSettings` is authoritative.

**Fix:** Delete `schema.py` or rename it to indicate status (e.g., `_legacy_schema.py`).

---

### [C4] `model_dump_flat()` produces list→JSON-string, breaking consumers
**File:** `models.py:944–945`
**Severity:** CRITICAL

```python
elif isinstance(v, list):
    result[key] = json.dumps(v) if v else v
```

Non-empty lists are serialized to JSON **strings**; empty lists remain Python lists. This means:
- `settings.get("mcp.servers")` returns a Python list
- `model_dump_flat()["mcp.servers"]` returns a JSON **string**

Code that uses the flat dict (e.g., any consumer switching from `Settings` to `AppSettings`) would silently break on lists. The `gets()` method in `settings.py` returns the raw value — consumers expect lists to be lists.

**Fix:** Store lists as lists in the flat dict. If a flat dict is truly required, use dot-notation flattening that preserves types:
```python
elif isinstance(v, list):
    for i, item in enumerate(v):
        result.update(_flatten(item, f"{key}.{i}"))
```

---

### [C5] Two parallel profile systems produce inconsistent state
**File:** `settings.py:19–62` + `settings.py:632–638`
**Severity:** CRITICAL

There are **two code paths** that apply profile overlays:
1. `load()` (line 632–638) — called on init and hot-reload, merges profile into `self.data`
2. `get_effective_settings()` (line 28–42) — called directly in `api/ws/handler.py:879`, loads base file + profile independently

`get_effective_settings()` does **not** go through the `Settings` class, so it misses:
- Migration logic
- Secret/env-key injection
- MCP server merging
- Defaults merging

A `/profile` command in the WebSocket handler calls `get_effective_settings()` to display the current profile, which may show a **different state** than what the `Settings` singleton holds.

Additionally, `switch_profile()` (line 52) writes `{"profile": name}` directly to `settings.json`, **bypassing the `Settings` class entirely**. No `save()` atomicity, no callback firing, no validation.

**Fix:** Make `get_effective_settings()` delegate to the global `Settings` instance. Make `switch_profile()` a method on `Settings` that calls `self.save()` and `self._fire_callbacks()`.

---

### [C6] Environment variable fallback for `azure-openai` produces invalid variable name
**File:** `settings.py:613`
**Severity:** CRITICAL

```python
env_keys = [f"{provider_name.upper()}_API_KEY"]
```

For `provider_name = "azure-openai"`, this produces `AZURE-OPENAI_API_KEY`. Environment variable names **cannot contain dashes** on most Unix-like systems or Windows. The fallback silently never works for this provider.

**Fix:** Normalize provider names before upper-casing:
```python
sanitized = provider_name.replace("-", "_").upper()
env_keys = [f"{sanitized}_API_KEY"]
```

---

### [C7] MCP server defaults diverge between DEFAULTS and MCPConfig
**File:** `settings.py:309–377` vs `models.py:679–743`
**Severity:** CRITICAL

The same MCP servers are defined in two places with different configurations:

| Server | `DEFAULTS` (settings.py) | `MCPConfig` (models.py) |
|--------|--------------------------|--------------------------|
| shell  | `args: [full path to server.py]` | `args: []` |
| obsidian | `args: ["-y", "obsidian-mcp", str(VAULT_DIR)]` | `args: ["-y", "obsidian-mcp"]` (no vault path) |
| skill  | `env.AMALGAM_DATA_DIR: str(DATA_DIR)` | `env.AMALGAM_DATA_DIR: ""` |
| screenshot | `args: [full path]` | `args: []` |
| system | `args: [full path]` | `args: []` |
| avatar | `args: [full path]` | `args: []` |

Depending on which code path applies defaults, servers may boot with incorrect args (missing vault path, missing data dir, or no script path).

**Fix:** Eliminate duplication. Define servers in one place only (e.g., a standalone `default_mcp_servers()` function) and reference it from both DEFAULTS and MCPConfig.

---

## HIGH

### [H1] Watcher fires callbacks on its own writes (self-trigger loop)
**File:** `settings.py:558–573`
**Severity:** HIGH

After `save()` writes atomically via `os.replace`, the watcher's 2-second poll detects the mtime change, calls `load()`, compares `old_data` (shallow copy) with `self.data`, and fires callbacks. This means every `settings.set()` → `save()` → watcher → `load()` → `_fire_callbacks()` creates a **duplicate callback invocation**. The first callback is explicit in `set()`, the second is from the watcher.

For expensive callbacks like MCP server reconnection (startup.py:96–116), this doubles the reconnect work on every settings change.

**Fix:** Either (a) suppress watcher callbacks after a programmatic write (track `self._dirty` flag), or (b) have `save()` update `self._last_mtime` so the watcher skips its own write.

---

### [H2] Shallow copy in watcher race check
**File:** `settings.py:569`
**Severity:** HIGH

```python
old_data = dict(self.data)   # shallow copy
self.load()
if self.data != old_data:
    ...
```

`dict(self.data)` is a shallow copy. If `self.data` is `{"a": {"b": 1}}`, the copy is `{"a": <ref to same inner dict>}`. If `load()` mutates the inner dict in-place (which it does via deep-merge), the reference in `old_data` sees the same mutation. The comparison `!=` would compare equal even if the structure changed.

Additionally, `load()` is called without holding a lock, so `self.data` can change between the copy and the comparison.

**Fix:** Use `copy.deepcopy()` for the comparison snapshot, and add a lock.

---

### [H3] No API key validation on any provider
**File:** `settings.py:575–641`, `models.py:24–31`
**Severity:** HIGH

`load()` silently accepts empty API keys. There is no:
- Warning when the active provider has an empty `api_key`
- Check that required credentials are present before setting the provider as active
- Validation that the key format matches expectations (e.g., starts with expected prefix)

For AWS/GCP providers, `access_key`/`secret_key` and `service_account_json` are also not validated.

This means a misconfigured provider is discovered only at runtime via an API error, giving a poor user experience.

**Fix:** Add a `validate_active_provider()` method (or Pydantic model validator) that warns if the active provider's credentials are empty. Check at boot time.

---

### [H4] `get_all()` returns mutable reference to internal data
**File:** `settings.py:701–702`
**Severity:** HIGH

```python
def get_all(self) -> dict:
    return self.data
```

Returns the internal `self.data` dict by reference. Any caller can mutate it, corrupting the global settings state without triggering `save()` or callbacks. Combined with thread safety issues, this is a latent corruption vector.

**Fix:** Return `copy.deepcopy(self.data)` or wrap in a read-only proxy.

---

### [H5] `Allow` callbacks list is not thread-safe
**File:** `settings.py:539–541, 709–714`
**Severity:** HIGH

`on_change()` appends to `self._callbacks` without a lock. `_fire_callbacks()` iterates over it without a lock. If a callback is registered from a thread (or if the watcher fires callbacks concurrently with registration), `_fire_callbacks()` may see a partially constructed list or raise `RuntimeError: list changed during iteration`.

**Fix:** Guard with a lock, or replace with `list(self._callbacks)` inside the iteration.

---

### [H6] `set()` creates empty dicts on intermediate missing keys
**File:** `settings.py:688–699`
**Severity:** HIGH

```python
for k in keys[:-1]:
    if k not in d or not isinstance(d[k], dict):
        d[k] = {}
    d = d[k]
```

If `k` exists but is a non-dict value (e.g., `"provider": "gemini"` — a string), this **drops the existing value** and replaces it with `{}`. Data loss is silent.

**Fix:** Check and raise/warn instead of silent overwrite:
```python
if k in d and not isinstance(d[k], dict):
    raise TypeError(f"Cannot descend into non-dict value at {'.'.join(keys[:i+1])}")
```

---

### [H7] `azure_openai` default shares one mutable object across instances
**File:** `models.py:201–211`
**Severity:** HIGH

```python
azure_openai: ProviderConfig = Field(
    default=ProviderConfig(...),  # <-- NOT default_factory
    alias="azure-openai",
)
```

`default=` creates a **single `ProviderConfig` instance** at class definition time. Every `LLMProviderConfig()` created from that point shares the same object. If any code mutates it (Pydantic v2 allows this by default), all instances are corrupted.

All other 17 providers correctly use `default_factory=lambda: ...`. This one outlier is a defect.

**Fix:** Change to `default_factory=lambda: ProviderConfig(...)`.

---

### [H8] `load()` deep-copies entire DEFAULTS on every call
**File:** `settings.py:740–748`, called at `594`
**Severity:** HIGH

```python
def _deep_merge(base, override):
    result = copy.deepcopy(base)  # Deep-copies ALL of DEFAULTS
    ...
```

`load()` is called:
1. At `__init__` (line 537)
2. Every watcher poll cycle (~every 2 seconds) (line 570)
3. On programmatic writes

Each call deep-copies the complete DEFAULTS dict (~200+ keys, nested 4+ levels). This is significant unnecessary GC pressure for a hot path.

**Fix:** Cache the deep-copied DEFAULTS and re-use it:
```python
_DEFAULTS_COPY = None
def _deep_merge(base, override):
    global _DEFAULTS_COPY
    if _DEFAULTS_COPY is None:
        _DEFAULTS_COPY = copy.deepcopy(DEFAULTS)
    result = copy.deepcopy(_DEFAULTS_COPY)
    ...
```

---

### [H9] `except Exception` catches too broadly in 5 locations
**File:** `settings.py:582, 628, 637, 670, 713` and `startup.py:54, 78, 144`
**Severity:** HIGH

All five `except Exception` blocks in settings.py catch `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`, and `StopIteration`. While Python's `asyncio.CancelledError` may also be swallowed, the pattern is dangerous.

**Fix:** Use specific exception types (e.g., `json.JSONDecodeError`, `OSError`, `FileNotFoundError`) wherever possible. At minimum re-raise `KeyboardInterrupt`/`SystemExit`:
```python
except Exception as e:
    if isinstance(e, (KeyboardInterrupt, SystemExit)):
        raise
    ...
```

---

## MEDIUM

### [M1] Two different `_deep_merge` implementations with different semantics
**File:** `settings.py:43–50` (module-level) vs `settings.py:740–748` (static method)
**Severity:** MEDIUM

- **Module-level** (line 43): shallow merge, no deep copy of leaf values
- **Static method** (line 740): uses `copy.deepcopy` for everything

`load()` calls the static-method version on line 594. `get_effective_settings()` calls the module-level version on line 41. Different merge behaviors for the same logical operation.

**Fix:** Unify into a single implementation, ideally using deep copy for safety.

---

### [M2] `switch_profile()` bypasses Settings singleton, writes raw without callback
**File:** `settings.py:52–62`
**Severity:** MEDIUM

```python
def switch_profile(name: str):
    path = Path(str(SETTINGS_PATH))
    settings = {}
    if path.exists():
        settings = json.loads(path.read_text())
    settings["profile"] = name
    path.write_text(json.dumps(settings, indent=2))
```

This reads the raw file, adds a `profile` key, and writes it back — completely bypassing the `Settings` class. No callbacks fire. No migration runs. The `Settings` instance only picks up the change when the watcher polls 0–2 seconds later.

**Fix:** Make `switch_profile` a method on `Settings` that calls `set("profile", name)`.

---

### [M3] `model_dump_flat()` resolves SecretStr but settings.py stores plain strings
**File:** `models.py:900–906`
**Severity:** MEDIUM

The flat-dump mechanism resolves `SecretStr` to plain text for backwards compatibility. But `settings.py` stores API keys as plain strings in `self.data` (no `SecretStr` wrapping). This means:
- Keys are always plain strings in memory (potential for log/history leakage)
- The `SecretStr` in models.py gives a **false sense of security** — the actual runtime data is never wrapped

**Fix:** Either commit to `SecretStr` by wrapping at load time, or remove `SecretStr` from models.py to avoid misleading readers.

---

### [M4] `TTSConfig` missing `stt_engine` field present in DEFAULTS
**File:** `models.py:379–398` vs `settings.py:179`
**Severity:** MEDIUM

DEFAULTS has `voice.stt_engine: "browser"` but `TTSConfig` does not include this field. It's only in `VoiceConfig` (line 438). The flat dict `voice.stt_engine` would work, but the typed model would silently drop it (unless `extra = "allow"` catches it).

**Fix:** Confirm that `stt_engine` belongs in `TTSConfig` or document why it's intentionally absent.

---

### [M5] `lipsync_enabled` appears in both `TTSConfig` and `VoiceConfig`
**File:** `models.py:385, 437`
**Severity:** MEDIUM

```python
class TTSConfig(BaseModel):
    lipsync_enabled: bool = Field(default=True, ...)  # line 385

class VoiceConfig(BaseModel):
    lipsync_enabled: bool = Field(default=True, ...)  # line 437
```

Two different models both own this field. The flat dict gives `voice.lipsync_enabled` (VoiceConfig) and `voice.tts.lipsync_enabled` (TTSConfig). Code reading one may not see writes to the other.

**Fix:** Keep it in one place (VoiceConfig) and remove from TTSConfig, or add a validator to keep them in sync.

---

### [M6] Migration infrastructure exists but no migration functions are defined
**File:** `settings.py:642–657`
**Severity:** MEDIUM

`CONFIG_VERSION = 1`, `_run_migrations()` loops `range(current, CONFIG_VERSION)`, and `getattr(self, f"_migrate_v{v}_to_v{next_v}", None)` looks for migrators. But no `_migrate_v0_to_v1` method exists. The loop `range(0, 1)` would iterate once, find no migrator, and set `config_version = 1` — effectively a no-op.

If version 1 was supposed to have a migration, it's missing. Future migrations may not be tested.

**Fix:** Either add `_migrate_v0_to_v1` (even if no-op with comment) or remove the migration machinery until it's needed.

---

### [M7] `Switch_profile` only accepts 4 hardcoded names but file contains arbitrary names
**File:** `settings.py:52–62`
**Severity:** MEDIUM

```python
if name not in ("token-friendly", "default", "quality", "custom"):
    raise ValueError(...)
```

This hardcoded list prevents programmatic or user-created profiles from being selected, even though the profile system itself has no such restriction. A user who manually creates `settings/profiles/my-custom.json` cannot activate it.

**Fix:** Validate that the profile file exists on disk instead of using a hardcoded allowlist.

---

### [M8] `Translate` section missing in Pydantic models
**File:** `models.py:1–954` vs `settings.py:396–401`
**Severity:** MEDIUM

DEFAULTS defines a `translation` section (enabled, source_lang, target_lang, base_url) but `AppSettings` has no `translation` field. With `extra = "allow"` (line 892), it passes through, but Pydantic won't validate it.

**Fix:** Add a `TranslationConfig` model and include it in `AppSettings`.

---

### [M9] `Telegram` allowed_users typing mismatch
**File:** `settings.py:168` vs `models.py:805`
**Severity:** MEDIUM

- `DEFAULTS`: `"allowed_users": []` — untyped, could be strings
- `models.py`: `allowed_users: List[int]` — validates as integers

If a user sets Telegram allowed users via the settings UI as strings (e.g., `["12345"]`), the Pydantic model rejects it. This would break profile loading with no clear error message.

**Fix:** Use `List[Union[int, str]]` or add a pre-validator to coerce strings to ints.

---

### [M10] VAD frame_size upper bound may be too low
**File:** `models.py:409`, `settings.py:182`
**Severity:** MEDIUM

```python
frame_size: int = Field(default=960, ge=160, le=960, description="VAD frame size in samples")
```

The upper bound equals the default. Any user-configurable higher value (e.g., 1920 for 60ms at 32kHz) would be rejected even if the VAD algorithm supports it.

**Fix:** Set `le=1920` or remove the upper bound and validate contextually.

---

### [M11] Deprecated keys still present in settings? Not directly, but `voice.active` is ambiguous
**File:** `models.py:463`
**Severity:** MEDIUM

`VoiceConfig` has `active: str = Field(default="", description="Active TTS voice name / ID")`. This field exists in many user settings files but is not in `DEFAULTS`. Its purpose is unclear: is it a voice ID, a voice name, or the active engine? The comment says "voice name / ID" which conflates two different things.

**Fix:** Rename to `preferred_voice_id` or clarify with a validated format.

---

## LOW

### [L1] Redundant `str()` wrapping around `SETTINGS_PATH` and `CHARACTERS_DIR`
**File:** `settings.py:34, 56, 496`
**Severity:** LOW

```python
Path(str(SETTINGS_PATH))   # SETTINGS_PATH is already str
Path(str(CHARACTERS_DIR))  # CHARACTERS_DIR is already Path
```

These are no-ops but suggest confusion about types. Clean up.

---

### [L2] Inconsistent import formatting with weird spaces
**File:** `settings.py:5–14`
**Severity:** LOW

```python
import json   # trailing space
import os 
import yaml 
...
from backend .core .paths import CHARACTERS_DIR ,SETTINGS_PATH ,PROJECT_ROOT ,VAULT_DIR ,DATA_DIR 
```

The spacing around dots in the last import line is unusual. Most imports use `from backend.core.paths import ...` (no spaces around dots). This inconsistency suggests auto-formatter issues or manual edits.

---

### [L3] `load()` applies profile overlay AFTER defaults merge, may override merged values
**File:** `settings.py:632–638`
**Severity:** LOW (but worth noting)

The order is:
1. `self.data = self._deep_merge(DEFAULTS, self.data)` (line 594)
2. Profile overlay: `self.data = _deep_merge(self.data, profile)` (line 636)

Step 1 merges defaults under loaded data. Step 2 overlays profile on top. If a profile key has the same name as a DEFAULTS key, it wins — which is intended. But profile values are not validated against DEFAULTS structure, so a profile could write garbage into any section.

---

### [L4] `get()` returns `default` for empty string dotpath
**File:** `settings.py:677–686`
**Severity:** LOW

```python
keys = dotpath.split(".")
```

`settings.get("")` returns `default` because `[""]` is not in `self.data`. This is probably fine but testable edge case.

---

### [L5] `_scan_characters_in` uses `os.listdir(str(base_dir))` instead of `base_dir.iterdir()`
**File:** `settings.py:464`
**Severity:** LOW

Minor style issue. `base_dir.iterdir()` is more Pythonic and avoids string conversion.

---

### [L6] Comment says "proper locking" but save() has no inter-process lock
**File:** `settings.py:659–660`
**Severity:** LOW

```python
"""Atomically save settings to disk with proper locking."""
```

The atomic write (`tempfile.mkstemp` + `os.replace`) prevents partial reads, but there is no lock. Two processes writing concurrently would silently overwrite each other. Since settings is typically single-process, this is low-risk but the docstring is misleading.

---

### [L7] `_watch_loop` catches OSError silently and continues
**File:** `settings.py:565–566`
**Severity:** LOW

```python
except OSError:
    continue
```

If the settings file is deleted and recreated, or permissions change, the watcher silently spins without logging. A periodic `logger.warning` would help diagnose file system issues.

---

### [L8] Mutable default in `ShellConfig.allowed_prefixes`
**File:** `models.py:501–516`
**Severity:** LOW (Pydantic v2 handles this)

```python
allowed_prefixes: List[str] = Field(default=[...])
```

Pydantic v2 deep-copies list defaults, so this is safe. But Pydantic v1 would share the mutable list across instances. Flagging for awareness.

---

### [L9] `flush()` + `fsync()` but no `fdatasync()` — metadata vs data sync
**File:** `settings.py:667–668`
**Severity:** LOW

```python
f.flush()
os.fsync(f.fileno())
```

`os.fsync()` syncs both data and metadata. `os.fdatasync()` (available on Linux) is faster because it skips metadata if the file size hasn't changed. Since the temp file is newly created, `fdatasync` may not help, but for future optimization consider it.

---

### [L10] No type hints for several module-level functions
**File:** `settings.py:19, 28, 43, 52`
**Severity:** LOW

`load_profile()`, `get_effective_settings()`, `_deep_merge()`, and `switch_profile()` lack return type hints.

---

### [L11] Empty `voice.model` in DEFAULTS but `ProviderConfig` defaults it to `""` — OK but fragile
**File:** `settings.py:74, 113, 117`
**Severity:** LOW

Several local providers (`ollama`, `llamacpp`, `koboldai`) have `"model": ""` in DEFAULTS. If activated without setting a model, API calls fail. Consider removing these empty defaults or adding a comment that they require user configuration.

---

## SUMMARY

| Severity | Count |
|----------|-------|
| CRITICAL | 7 |
| HIGH     | 9 |
| MEDIUM   | 11 |
| LOW      | 11 |
| **Total** | **38** |

**Top 3 priorities:**
1. **Thread safety (C1)** — data races on every `set()`/`load()` pair
2. **Either integrate or delete models.py (C2)** — 954 lines of dead Pydantic code
3. **Fix `get_effective_settings()` bypass (C5)** — dual path produces inconsistent state
