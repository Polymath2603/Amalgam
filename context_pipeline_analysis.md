# Context Pipeline — Code Quality Analysis

**Date:** 2026-06-18  
**Scope:** `backend/core/context/` (package), `backend/core/context_builder.py` (legacy), `backend/core/context_manager.py`, `backend/core/utils/tokens.py`

---

## 1. Critical Architecture Issue: Duplicate `ContextBuilder`

**Severity: CRITICAL**  
**Files:** `backend/core/context/builder.py` and `backend/core/context_builder.py`

There are **two** `ContextBuilder` classes with entirely different interfaces:

| Aspect | `backend/core/context/builder.py` (package) | `backend/core/context_builder.py` (legacy) |
|--------|---------------------------------------------|--------------------------------------------|
| Constructor | `__init__(templates_dir=None)` | `__init__(settings=None)` |
| Build method | `build_system_prompt(character, intent, vault_context)` + `build_tool_section(tools, intent)` | `build(tools, history, user_msg, character_id, ...)` → returns `list[messages]` |
| Token estimation | Uses `estimate_tokens` from `budgets.py` (simple heuristic) | Uses `estimate_tokens` from `utils/tokens.py` (tiktoken-aware) |
| Templates | Jinja2 `PackageLoader` (system_prompt.j2, tool_section.j2) | Jinja2 `BaseLoader` with inline template string |
| Used by | **Nobody** — only its own `__init__.py` exports it | `agent/core.py`, `deps.py` |

### Impact
- The package-based `ContextBuilder` (`core/context/builder.py`) is **dead code**. It was started as a refactor but never wired into the application.
- The legacy `ContextBuilder` (`core/context_builder.py`) is the only one in use.
- Anyone maintaining the codebase must know both classes exist, and the package version is a trap for new developers who follow the package import.

### Recommendation
- Either finish the migration and remove the legacy class, or delete the unused package class and its templates.

---

## 2. Module-Level Singleton Mutation

**Severity: HIGH**  
**File:** `backend/core/context_builder.py`, line 14  
```python
_user_profile = UserProfile()  # module-level singleton
```

### Problems
1. **Module-level import-time instantiation**: `UserProfile()` is created when the module is first imported. This means any import of `context_builder` triggers I/O (file reads for the user profile) at import time, which can cause:
   - Circular import issues (if `UserProfile` imports something that imports `context_builder`)
   - Slow startup
   - Hidden side effects from a simple import
2. **No lifecycle management**: The singleton persists for the entire process lifetime. If settings change or user profile is updated, the stale singleton remains in memory.
3. **Testability**: Impossible to mock cleanly since it's captured at module load time.

### Recommendation
- Use a factory function or lazy property on `ContextBuilder` instead.

---

## 3. Token Estimation Duplication

**Severity: HIGH**  
**Files:** `backend/core/context/budgets.py:141-166` vs `backend/core/utils/tokens.py:72-94`

### Problems
- `budgets.py` has its own `estimate_tokens()` that uses a flat 4-char heuristic with model-specific fudge factors.
- `utils/tokens.py` has a more sophisticated `estimate_tokens()` with actual tiktoken support, SentencePiece calibration, and encoding caching.
- The package `context/builder.py` imports from `budgets.py` (line 13), not from `utils/tokens.py`.
- The legacy `context_builder.py` uses `utils/tokens.py` (line 9).
- The `context_manager.py` also uses `utils/tokens.py`.

### Impact
- Inconsistent token counting depending on which path code takes.
- The package-based `ContextBuilder` may over/under-count tokens by 10-40% vs the real tokenizer, leading to context overflow or wasted space.

### Recommendation
- Delete the `estimate_tokens` copy in `budgets.py` and import from `utils/tokens.py` everywhere.

---

## 4. Package `context/` — Dead Code / Incomplete Refactor

**Severity: MEDIUM**  
**Files:** `backend/core/context/` (entire package)

### Problems
1. **Unused `VaultInjector`** (`vault_injector.py`): A separate class for vault rules injection, but the legacy `context_builder.py` implements vault reading inline (lines 122-148). Two different vault injection implementations exist.
2. **Unused `BudgetManager`**: The `context/budgets.py` has a sophisticated proportional allocation model, but it's never used from the actual request path.
3. **Unused templates** (`templates/system_prompt.j2`, `templates/tool_section.j2`): Only loaded by the unused `ContextBuilder`.
4. **`context/__init__.py` exports all four classes** (`ContextBuilder`, `BudgetManager`, `ContextBudget`, `VaultInjector`), but no consumer imports them.

---

## 5. Legacy `context_builder.py` — God Method

**Severity: HIGH**  
**File:** `backend/core/context_builder.py`, method `build()` (line 150-200)

### Problems
- `build()` is **170-line method** (when including all sub-calls) that does everything: loads character config, builds character prompt, injects skills, injects vault rules, builds tools section, builds relationship section, renders Jinja2, truncates system prompt, and assembles the full message list.
- It delegates to 8+ `_build_*` private methods, but the orchestration is still monolithic.
- The character prompt builder (`_build_character_prompt`, line 281) is itself 120+ lines.

### Recommendation
- Split into a proper builder chain: `CharacterPromptBuilder`, `ToolSectionBuilder`, `VaultSectionBuilder`, `AvatarSectionBuilder`.
- Use the dataclass-based `ContextBudget` pattern (from the dead package!) to manage proportional allocation instead of hard-coded truncation.

---

## 6. `context_manager.py` — Hard-Coded Priority & Edge Cases

**Severity: MEDIUM**  
**File:** `backend/core/context_manager.py`

### Problems

#### 6a. Available budget can go negative (line 82)
```python
available -= sys_tokens
```
If `sys_tokens > available`, the system prompt is truncated and `sys_tokens` is recalculated, but if the new `sys_tokens` is still close to `available`, no check is done. Every subsequent subtraction assumes `available >= 0`.

#### 6b. Relevant context selection is O(n²) (lines 93-109)
```python
for item in reversed(relevant):
    ...
    relevant_tokens = sum(estimate_message_list_tokens(keep, model))
```
`estimate_message_list_tokens` iterates the entire `keep` list **on every iteration**, making this O(n²). For large relevant context lists, this is wasteful.

#### 6c. No validation of `relevant` item structure (lines 93-109)
Uses `item.get("content", "")` but never checks for `"role"` key which `estimate_message_list_tokens` expects.

#### 6d. Priority inversion potential
The method docstring states: `summary > relevant > relationship > history > vault`. But if `summary` is absent, its budget flows to `relevant`, which is correct. However, if `history` is massive (as is common), it can consume all remaining budget, leaving zero for `vault_content`. The `vault_content` truncation at line 131 would then produce `truncate_to_token_limit(content, 0, model)` which returns `""` (handled at line 99-100 of tokens.py, so safe, but silently drops vault content).

#### 6e. No budget reservation for system prompt overhead (line 77)
`SYSTEM_PROMPT_OVERHEAD` (50 tokens) is added to the system prompt estimate, but there's no corresponding overhead for the user message (only `TURN_OVERHEAD` at 8 tokens). The overhead accounting is inconsistent.

---

## 7. Missing Error Handling

### 7a. `context/builder.py` — Swallowed template loading exception (line 40-42)
```python
except Exception:
    logger.warning("Template directory not found, using fallback")
    self.env = None
```
Silently catches **all** exceptions. If the template directory exists but has a permission error, or if `PackageLoader` raises an `ImportError` for a different reason, it's masked.

### 7b. `context/builder.py` — Swallowed rendering exceptions (lines 86-88, 141-143)
```python
except Exception as e:
    logger.warning(f"Template rendering failed: {e}, using fallback")
```
Again, catches all exceptions. A template syntax error would be silently degraded.

### 7c. `context_builder.py` — Vault section error handling (lines 145-146)
```python
except Exception as e:
    logger.warning(f"Failed to read rules.md: {e}")
```
Bare `Exception` catch. At least it logs, but there's no differentiation between file-not-found (expected), encoding errors (misconfiguration), or permission errors (environment issue).

### 7d. `vault_injector.py` — Silent fallbacks everywhere (lines 37, 49, 68, 79)
Every `extract_*` method returns `""` on any error. This is safe but makes debugging silent failures very difficult. No differentiation between "no vault configured" vs "vault exists but is unreadable".

---

## 8. Code Quality / Anti-patterns

### 8a. Inconsistent whitespace and formatting in `context_manager.py` (lines 1-17)
```python
import logging 
from typing import List ,Dict ,Optional 
```
Spaces before newlines, spaces after commas inside type hints. Python formatting is inconsistent throughout the file.

### 8b. `context_manager.py` uses ` ->dict :` type hint with no capitalization
Line 47: `)->dict :` — should be `-> dict:`.

### 8c. Magic numbers
- `context/budgets.py`: `50` (safety margin, line 89), `10` (minimum tokens, line 111)
- `context_manager.py`: `50` (safety margin, line 73), `SYSTEM_PROMPT_OVERHEAD = 50` (line 13)
- `context_builder.py`: `200` (max vault tokens, line 134), `1500` (max system prompt tokens, line 182)

These should be named constants or config values.

### 8d. `context/builder.py` — `truncate_to_budget` uses crude truncation (lines 177-195)
```python
max_chars = int(len(text) * (max_tokens / estimated))
return text[:max_chars].rsplit(' ', 1)[0] + "..."
```
This is a linear ratio approximation. For a 2000-token text being truncated to 1000 tokens, it assumes the token-to-char ratio is uniform, which is often false (especially with code, markdown, or CJK text). The `utils/tokens.py` version uses binary search (`truncate_to_token_limit`) which is correct but slower.

### 8e. `context/budgets.py` — Allocation sum may exceed available (lines 107-113)
```python
for section, proportion in pattern.items():
    tokens = int(self.available * proportion)
    budgets[section] = ContextBudget(
        section=section,
        tokens=max(tokens, 10),
        priority=proportion
    )
```
Because of `int()` flooring and the `max(tokens, 10)` floor, the sum of all section tokens can exceed `self.available`. For example if `available=1000` and proportions sum to 1.0, `int(1000*0.15)=150`, etc., but the floor of 10 tokens inflates small sections. The total could exceed 1000.

---

## 9. Performance Bottlenecks

### 9a. `context_manager.py` — O(n²) relevant selection (lines 93-109)
As noted in 6b, `estimate_message_list_tokens` is called inside the loop, iterating the entire accumulated list each time. For `n=100` relevant items, this is ~5000 token estimates instead of ~100.

### 9b. `context_builder.py` — `_get_available_animations` walks disk every build (lines 95-115)
Every call to `build()` → `_build_character_prompt()` → `_get_available_animations()` does `os.listdir()` on up to 4 directories. This is disk I/O on every prompt build. For a chat application, this can be called every user message.

### 9c. `context_builder.py` — Vault file read on every build (lines 122-148)
`_build_vault_section()` reads `rules.md` from disk on every single prompt build. For a chat application, this is unnecessary I/O.

### 9d. `context/builder.py` — `PackageLoader` on every class instantiation
`PackageLoader('backend.core.context', 'templates')` creates a new loader every time a `ContextBuilder` is created. The loader scans the package each time.

---

## 10. Design Improvement Opportunities

### 10a. Unify into a single pipeline
The ideal design would be:
```
ContextPipeline
├── CharacterPromptProvider    (from character config)
├── VaultProvider              (cached markdown reader → vault_injector.py)
├── ToolSectionProvider        (from tools list → tool_section.j2)
├── SkillProvider              (from MDSkillLoader)
├── MemoryProvider             (summary + relevant)
├── RelationshipProvider       (from relationship db)
├── HistoryProvider            (from conversation history)
├── BudgetManager              (proportional allocation → budgets.py)
└── ContextAssembler           (orchestrates, truncates, assembles messages)
```

### 10b. Cache vault reads
Read `rules.md` once and invalidate on file change (inotify or mtime check).

### 10c. Use `functools.lru_cache` on `estimate_tokens`
The `utils/tokens.py:estimate_tokens` is called many times per prompt build with the same model string. Caching would help, but careful with memory for large texts.

### 10d. Replace `PackageLoader` with `FileSystemLoader`
For development, `FileSystemLoader` with auto-reload is more ergonomic. For production, the templates could be compiled once.

### 10e. Add formal context assembly validation
A `ContextAssemblyResult` dataclass with `used_tokens`, `total_budget`, `sections`, `warnings` would make debugging context overflow much easier.

---

## Summary Table

| # | File | Issue | Severity |
|---|------|-------|----------|
| 1 | `context/builder.py` + `context_builder.py` | Duplicate `ContextBuilder` classes | CRITICAL |
| 2 | `context_builder.py:14` | Module-level singleton with I/O at import | HIGH |
| 3 | `budgets.py` vs `utils/tokens.py` | Duplicate token estimation functions | HIGH |
| 4 | `context/` (package) | Dead code / incomplete refactor | MEDIUM |
| 5 | `context_builder.py:150-200` | God method with too many responsibilities | HIGH |
| 6 | `context_manager.py` | Budget edge cases, O(n²) algorithm, inconsistent overhead | MEDIUM |
| 7 | Multiple files | Bare `except Exception` swallowing errors | MEDIUM |
| 8 | Multiple files | Magic numbers, formatting, anti-patterns | LOW |
| 9 | `context_builder.py:95-115` | Disk I/O on every prompt build | MEDIUM |
| 10 | Multiple files | Missing caching, no pipeline abstraction | MEDIUM |
