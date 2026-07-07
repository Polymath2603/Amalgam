# Audit Report

This replaces 18 separate self-authored "audit" and "sweep" report files
(AGENT_AUDIT.md, FINAL_SWEEP.md, TEST_REPORT.md, TODO_REPORT.md, and 14
others) that collectively claimed "0 remaining findings" and "710 passed,
0 failed" while the actual frontend test suite was 100% self-referential —
every one of the 8 `webui/tests/*.test.js` files imported only from
`vitest`, never from the real source files they claimed to test. This
document is the honest replacement, written after rebuilding the test
suite for real and using it to find actual bugs.

## What was actually wrong

**The frontend test suite was entirely fake.** All 8 test files redefined
local copies of the logic they claimed to test instead of importing the
real source. The closest thing to a real check (`TEST_REPORT.md`'s "33
JavaScript files: all passed") was `node --check` — syntax validation only,
not execution. Rewritten from scratch: every file now imports and exercises
the real production code. Final state: **171/171 real tests passing**
across all 8 files.

**The backend test suite was largely real**, with real imports and
meaningful assertions — this was the one part of the original claims that
held up. Verified by actually executing it (not just reading it) after
building offline-but-functional dependency shims for what couldn't be
`pip install`ed in this environment: 751/781 passing for real, with the
remaining 23 honestly blocked by things that need real network access
(`faster-whisper`'s model weights) or a real Textual app/Pilot test
harness that isn't worth faking.

## Real bugs found and fixed

Found by actually running things, not by reading code and guessing.

**Backend:**
1. **`MetricsCollector` silently dropped ~75% of writes under concurrent
   load.** No lock around schema init or the insert itself; concurrent
   turns finishing close together hit `database is locked` and the error
   was swallowed at debug level — invisible in production. Fixed with an
   `asyncio.Lock` around both (`backend/core/metrics.py`).
2. **`CompanionEngine` crashed when started from a sync context** (e.g.
   the CLI, via `backend.core.deps.get_shared()`) — `asyncio.create_task()`
   with no running event loop. Added a guard that logs and skips instead
   of crashing the caller (`backend/core/companion/engine.py`).
3. **Three missing dependencies** that would crash a clean install:
   `cachetools` (used by `litellm_provider.py`), `prompt_toolkit` and
   `rich` (used by the CLI) — none were in `requirements.txt`.
4. **Corrupted syntax in 3 production files** from what looks like an
   automated API-key redaction pass gone wrong: a malformed dict literal
   in `backend/api/routes/setup.py` (4 provider entries lost their
   `needs_api_key`/`default_model`/`models` fields), and two function
   signatures in the TTS layer (`router.py`, `elevenlabs_provider.py`)
   where `api_key: str` became `api_key: "REDACTED"`, dropping the `model`
   parameter entirely. All three were `SyntaxError`s — the files couldn't
   even be imported.
5. **`tests/cli/test_cli.py` had the same corruption** (one more
   `SyntaxError`, same root cause) — fixed.
6. **`CharacterSchema`** (Pydantic validator) was dead code: a nested
   schema that didn't match the actual flat YAML format used by every real
   character file, never imported anywhere. Rewritten to match reality and
   wired into the loader.
7. **27 of 28 bundled character personas were copyrighted third-party
   IP** (Batman, Frieren, Anya & Yor Forger, Nezuko, L, Senku, and more),
   including 15–20MB VRM model files under VRoid Hub fan-content licenses
   that explicitly disallow redistribution. Removed; replaced with 3
   original characters (Sable, Wren, Juno) sharing the existing
   non-IP default avatar model.
8. **No `.gitignore` existed at all** — `__pycache__`, `node_modules`,
   and `*.db` files would all get committed. Added one and cleaned out the
   31 `__pycache__` dirs / 200 `.pyc` files already present.
9. **No GitHub Actions CI existed** despite being referenced as failing —
   it simply didn't exist. Added `.github/workflows/ci.yml` (backend
   pytest, CLI pytest, frontend vitest, a non-blocking voice-dependency
   job, and a full-repo Python syntax check).

**Frontend:**
10. **`AdvancedLipSync` crashed on every frame in its main operating
    mode.** When no TTS viseme schedule is set (i.e. live-microphone/FFT
    mode — the actual fallback path, not an edge case), `analyze()`
    returned `{viseme, mouthOpen, intensity}` while the consumer
    (`avatar.js::setViseme`) reads `frame.shape.open/.width/.round` —
    guaranteed `TypeError` on every animation frame. Root cause: two
    *different, incompatible viseme-naming taxonomies* existed
    side-by-side (`advanced-lipsync.js`'s own `A`/`I`/`U`/`E`/`O`/`M`/...
    scheme vs. the shared `visemes.js` extended scheme), blended as if
    they were comparable. Fixed by removing the duplicate taxonomy
    entirely and unifying both code paths on one return shape.
11. **`settings.js` threw `ReferenceError` on every load** —
    `window.loadCompanionSettings = loadCompanionSettings` referenced a
    function that was never defined anywhere in the file (or the repo).
    Dead leftover from a refactor; removed.
12. **`_formatDate`'s own error-fallback could itself throw** (the catch
    block called `String(ts)`, which calls `.toString()` again — if that's
    what threw the first time, it throws again). Made the fallback safe.
13. Two real, narrowly-scoped findings from `SECURITY_REVIEW.md` (kept,
    updated — see that file): one fixed (escaping gap in tool-call
    rendering, though not actually reachable through the current regex);
    two left honestly unfixed because they need a real authentication
    system to address at all (see below).

**`loop.zip` (the n8n multi-agent harness, packaged separately from the
above):** its own README already disclosed its placeholders honestly,
unlike the other project. Fixed the concrete one anyway — `Load System
Prompts` was a stub returning `{ note: 'wire this up' }`; both n8n
workflows now actually read each agent's real `system_prompt.md` from
disk and reference it from every `Call: <Agent>` node (16 nodes across 2
workflows), with a correctly-sequenced connection graph and clear
`[ERROR: ...]` output instead of silent failure if a file can't be read.
Also de-duplicated the package itself — the same content existed twice
(loose files at the zip root, and again nested inside `ai-company.zip`);
consolidated to one canonical `ai-company/` folder.

## What's still genuinely unresolved (not fixed, on purpose)

- **No authentication on any API or WebSocket endpoint.** Anyone on the
  network can connect, change settings, or read/inject into any session
  by guessing a `session_id`. Fixing the symptom (e.g. validating
  session ownership) without first having a concept of "the authenticated
  caller" would be a fix that looks complete but isn't — see
  `SECURITY_REVIEW.md` M1–M3. This needs a real, if minimal, auth layer
  as its own piece of work.
- **The "5-partition memory" and "14-emotion avatar" framing** from the
  original feature brainstorm don't literally exist as 5/14 identically-
  named things — they exist as a different, real architecture that
  satisfies the same intent (memory: see `backend/core/memory/__init__.py`
  and the README's Memory Architecture table; avatar: 25 emotions mapped
  onto 5 VRM base expressions, no 52-blendshape ARKit auto-detection).
  Documented explicitly rather than left as a silent gap.
- **`VRMAnimation`'s full GLTF-parsing pipeline** (`_parseAnimation`,
  `VRMAnimationLoaderPlugin.afterRoot`) isn't covered by the test suite —
  it needs a real `.vrma` binary fixture and a real three.js `GLTFLoader`
  to mean anything; the retargeting math it calls into
  (`createHumanoidTracks`/`createExpressionTracks`/`createAnimationClip`)
  *is* covered.
- **`tests/cli/test_tui.py`'s `Pilot`-based integration tests** (23 of
  them) need the real `textual` package's actual async App test harness.
  Faithfully simulating that would itself be the kind of test theater this
  audit removed elsewhere, so they're left for real CI (which has network)
  rather than faked. The non-Pilot unit tests in the same file (command
  registry, fuzzy filtering) are real and pass.
- **`backend/tests/test_voice_pipeline.py`'s `faster-whisper` tests**
  need the real model weights, which need network. Same reasoning.

## Test infrastructure notes

This environment had no network access, so dependencies that aren't
already present couldn't be `pip install`ed or `npm install`ed. Where a
test genuinely needed one of those (pydantic, aiosqlite, structlog,
vaderSentiment, rank_bm25, cachetools, httpx, litellm, fastapi,
prompt_toolkit, rich, textual on the Python side; vitest, three.js,
@pixiv/three-vrm, and a small real DOM implementation on the JS side),
a same-API-surface stand-in was built — real logic where the logic itself
was the point (e.g. aiosqlite's async wrapper is a real `sqlite3` bridge;
rank_bm25's `BM25Okapi` is the real scoring formula), honest "not
implemented" failures where faking the behavior would defeat the purpose
of testing it (e.g. `litellm.acompletion`, Textual's `Pilot`). None of
this offline scaffolding ships — `requirements.txt`, `requirements-voice.txt`,
and `package.json` declare the real packages; CI installs and runs against
those for real, with network.

## Addendum — session 2: AI Company plugin, TUI/WebUI, and this project's own archival

This session added a new, optional feature (the AI Company plugin) and
real visual/functional gaps in the TUI and WebUI, per a decision to bring
Amalgam to a genuine "it works" state before archiving it and moving
forward as a Hermes Agent plugin instead of a standalone platform (see
`LEGACY_NOTICE.md`).

### What was added

- **`backend/plugins/ai_company/`** — a normal `BasePlugin` that POSTs the
  user's message to an n8n webhook (the separate AI Company harness) and
  injects the returned plan into the system prompt via the existing
  `on_system_prompt` hook. Modes: `off` / `auto` (complex tasks only,
  via the same keyword heuristic as `BasicAgent._classify_intent`) / `on`.
  Fails silently and falls back to normal operation if n8n is unreachable
  or times out — this is meant to be a strict enhancement, never a hard
  dependency. Also registers a `run_company` tool for one-off requests.
- **TUI**: `/mcp` (list/connect/disconnect/tools) and `/company`
  (status/on/off/auto/run) are now real, wired commands — previously
  `/mcp` existed only as a settings-menu entry point, not a slash command,
  and `/company` didn't exist. Added a live AI Company status glyph to the
  header (`◑` auto, `⚡` on, `⚙` running, `✓` done, `✗` error), polled
  every 10s plus updated synchronously during an in-flight turn.
- **WebUI**: a new header toggle button (next to the mic/speaker icons)
  cycling off → auto → on, with a status-colored badge reflecting live
  `company:start`/`company:done`/`company:error` WebSocket events. New
  "AI Company" settings category (mode, webhook URL, timeout, plan token
  budget).
- **`/vault` and `/direct`** — added to the TUI first, then found to be
  missing from the WebUI's WS handler entirely (a real gap — same command
  existing in one client but not the other). Added there too.

### Real bugs found and fixed while building this (not pre-existing — introduced and caught within this same session)

1. **A stray `]` left the TUI's command-registry list unterminated** after
   an in-progress edit was interrupted by a conversation detour —
   `SyntaxError: '[' was never closed`. Caught immediately by the routine
   post-edit syntax sweep, fixed before it could have shipped.
2. **`vault.search()` was called with a `k=` keyword that doesn't exist**
   (real signature: `search(query, max_results=5)`, returning
   `{"filename", "score", "snippet", "size"}` — no `title`, no `content`,
   no `path` key). Would have thrown `TypeError` on every `/vault` call.
   Caught by writing a real, direct reproduction against `VaultManager`
   before trusting the fix on inspection alone.
3. **`/direct` initially read/wrote a `orchestrator.enabled` settings key
   that nothing in the entire codebase reads** — a leftover concept from
   the original feature brainstorm ("direct mode, /direct command") that
   was never actually implemented as a real toggle anywhere. Grepping the
   full backend confirmed zero references outside the line I'd just
   written. Rather than ship a command that prints a confident-sounding
   success message and does nothing, traced the real, already-existing
   `AgentFactory`/`agent.type` mechanism (`basic` vs `reflective_planning`,
   already wired at startup in `backend/core/deps.py`) and added a genuine
   `set_agent_type()` that swaps the live `_shared["agent"]` instance at
   runtime. Verified end-to-end with a real instance swap (not just
   read-the-code trust) and a new `TestSetAgentType` class in
   `backend/tests/test_deps.py` (5 new tests, all passing for real).
4. **Two stale/wrong links in the pre-existing "Similar Projects" section**
   of `README.md`, caught by fact-checking rather than assuming prior
   content was accurate: `t41372/Open-LLM-VTuber` pointed at an old
   personal-namespace URL — the project moved to the `Open-LLM-VTuber`
   org, and the original author's later re-fork of their own username for
   archival purposes means the old link no longer reliably redirects to
   the active project. `t41372/amica` was simply the wrong owner — Amica
   is `semperai/amica`; t41372 made Open-LLM-VTuber, a different project
   entirely. Both fixed to the correct, current canonical URLs.
5. **A fabricated placeholder GitHub URL** (`github.com/YOUR_ORG/ai-company`)
   was written into the new AI Company README section and caught before
   being left in — replaced with an accurate description of where that
   package actually lives (shipped alongside Amalgam, not hosted anywhere).

Items 3–5 are exactly the "confident liar" pattern this whole audit exists
to catch, this time caught in code written during the audit itself rather
than in the original handoff — the fix for that is the same either way:
verify against the real API/repo before trusting a plausible-looking
line, and say so plainly when a check reveals it was wrong.

