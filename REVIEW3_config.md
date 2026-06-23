# REVIEW 3 — Config Layer Final Verification

**Reviewer:** Round 3 (independent pass)
**Scope:** `settings.py`, `models.py`, `character_schema.py`, `deps.py`, `startup.py`
**Previous rounds:** Round 2 found 38 issues → 12 remained → Snail fixed them.
**Goal:** Zero issues remain.

---

## BUG FOUND (critical) — settings.py lines 596-602

### `changed` variable unbound in `_watch_loop` → watcher thread crashes

**Location:** `backend/core/config/settings.py`, method `_watch_loop`, lines 586-604

```python
if mtime > self._last_mtime:                # line 596
    self._last_mtime = mtime
    with self._lock:
        old_data = copy.deepcopy(self.data)
        self.load()
        changed = self.data != old_data      # line 601 — assigned HERE only
if changed:                                  # line 602 — NameError when condition is False
    logger.info("Settings file changed, hot-reloading")
    self._fire_callbacks()
```

**Problem:** `changed` is only assigned inside the `if mtime > self._last_mtime:` block. When the file has **not** changed since the last check (`mtime <= self._last_mtime`), which is the common case (polling every 2 seconds), the variable `changed` is never bound. On line 602, `if changed:` raises `NameError`.

**Impact:** The watcher daemon thread crashes silently on its very second iteration (~2 seconds after startup). Hot-reload of settings never works. Since it's a daemon thread, the app continues running but without file-watching capability.

**Verified:** Confirmed via reproduction script — second iteration with unchanged mtime raises:
> `NameError: cannot access local variable 'changed' where it is not associated with a value`

**Fix:** Either initialize `changed = False` before the `if mtime > self._last_mtime:` block, or move the `if changed:` block inside it.

---

## MINOR — character_schema.py line 13

### Unused import `Enum`

```python
from enum import Enum  # line 13 — never used
```

`Enum` is imported but never referenced in the file. Clean it up.

---

## OBSERVATIONS (not blockers, but worth noting)

### 1. Duplicate `_deep_merge` implementation

- Module-level function `_deep_merge` at `settings.py:31-43`
- Static method `Settings._deep_merge` at `settings.py:838-851`

Both have identical logic. The module-level fn is called at line 683 (`_deep_merge(self.data, profile)`) and the static method is called at line 637 (`self._deep_merge(DEFAULTS, self.data)`) and line 848 (`Settings._deep_merge(result[k], v)`). These could be unified to avoid maintenance drift.

### 2. `opencode` in `active` Literal but no provider field

In `models.py` line 76, the `active` Literal of `LLMProviderConfig` includes `"opencode"`, but there is no corresponding `opencode: ProviderConfig = Field(...)` entry in the class (lines 79-235). All other Literal values have a matching field. This works today only because `LLMProviderConfig` has `extra="allow"`. Inconsistent design.

### 3. `_merge_mcp_servers` uses subscript access without `.get()`

```python
defaults_by_name = {s["name"]: s for s in DEFAULTS.get("mcp", {}).get("servers", [])}
user_by_name = {s["name"]: s for s in user_servers}
```

If any MCP server entry lacks a `"name"` key, this raises `KeyError`. While all default servers have `"name"`, user-provided entries could theoretically lack it. Consider `s.get("name", "")`.

### 4. `VoiceConfig._sync_deepgram_aliases` always triggers on first call

In `models.py:499-504`, the identity check `self.deepgram is not self.deepgram_stt` is always `True` on initial construction because `default_factory` creates distinct instances. The assignment runs every time. This is functionally harmless but the guard never short-circuits in practice.

---

## VERIFICATION SUMMARY

| File | Lines | Status |
|------|-------|--------|
| `settings.py` | 1-1003 | **1 critical bug** (changed unbound), 2 observations |
| `models.py` | 1-971 | Clean (2 observations) |
| `character_schema.py` | 1-142 | **1 minor** (unused Enum import) |
| `deps.py` | 1-269 | Clean |
| `startup.py` | 1-174 | Clean |

### Previous fix references checked

| Tag | Location | Status |
|-----|----------|--------|
| C2 | settings.py:692,763; deps.py:105 | OK |
| C5 | settings.py:798,964; deps.py:54 | OK |
| C6 | settings.py:657 | OK |
| H1 | settings.py:714; deps.py:130 | OK |
| H2 | deps.py:186-188 | OK |
| H3 | settings.py:925 | OK |
| H4 | settings.py:779 | OK |
| H6 | settings.py:744; deps.py:177 | OK |
| H7/N2/N8 | startup.py:17 | OK |
| H10/N1 | startup.py:58 | OK |
| L1 | deps.py:117 | OK |
| M2/M7 | settings.py:797 | OK |
| M14 | deps.py:253 | OK |
| N2 | startup.py:81 | OK |
| N3 | startup.py:37,85 | OK |
| N4 | startup.py:71,121 | OK |
| N5 | settings.py:826; deps.py:54 | OK |
| N7 | models.py:499-504 | OK |

---

## VERDICT

**NOT CLEAN.** One critical runtime bug (watcher thread `NameError`) and one minor issue (unused import) remain. The `changed` variable bug was missed by all three previous review rounds and is a regression in the code as it stands.
