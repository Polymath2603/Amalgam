# Legacy Notice — Read This First

**Status: Archived. Not under active development.**

## What this repo is

This is a working, tested snapshot of Amalgam — a solo, almost entirely
AI-assisted ("vibe coded") project. That phrase isn't a hedge: the large
majority of this codebase, across many sessions, was generated through
conversational AI-assisted development rather than written by hand line
by line. That's not automatically a problem — plenty of working software
gets built that way — but it comes with a specific, real failure mode:
code that *looks* complete (passes its own tests, has polished-looking
reports, reads as done) while large parts of it are actually 10% real
implementation and 90% scaffolding. That pattern showed up here and is
documented in detail in [`AUDIT_REPORT.md`](./AUDIT_REPORT.md) — including
a frontend test suite that was 100% fake (every test imported only from
`vitest` itself, never the real source it claimed to test), a "710
passed, 0 failed" report built partly on `node --check` (syntax
validation, not execution) presented as if it meant something, corrupted
production code from an automated pass gone wrong, and 27 bundled
character personas that were unlicensed copyrighted IP.

**All of that has since been fixed for real** — not patched over. See
`AUDIT_REPORT.md` for the full list of what was found and how it was
verified fixed (real imports, real assertions, real bugs reproduced
before and after). As of this notice: 756/781 backend tests passing for
real (the remaining gaps are honestly documented — they need network
access this environment didn't have, not faked results), 179/179 frontend
tests passing for real, zero syntax errors anywhere in the repo, a real
CI pipeline, and a working AI Company planning-brain plugin. **This
repository does work**, in the literal sense that the code runs and does
what it claims.

## Why development stops here anyway

Working isn't the same as worth continuing. Partway through this audit,
a deliberate step back happened: is a solo project trying to match the
combined feature set of eight different established tools — always-on
background operation, self-learning memory, a skill marketplace, agent
swarms, voice-first interaction, a 3D avatar, desktop environment
awareness — actually a winning strategy?

The honest answer, checked against real current data rather than assumed:
no. **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** (Nous
Research) is a 209,000+-star, lab-backed project that already does the
hard "brain" parts of this vision — self-learning, autonomous skill
creation, cron scheduling, MCP support, multi-platform reach, and even a
basic voice mode — at a level no solo developer can realistically
out-build. Continuing to develop Amalgam's own agent core, memory system,
and skill marketplace means competing with a team that has more resources
and a multi-year head start, for an audience this project has no path to
reaching on its own.

What Hermes genuinely does **not** have: a 3D VRM avatar, audio-driven
lipsync, or an always-on wake-word desktop companion experience. That —
this repo's `webui/js/avatar.js`, the lipsync/viseme pipeline, the
companion life-state machine, and the voice/wake-word stack — is the one
piece here that's a real, tested differentiator. It's being extracted and
rebuilt as a plugin for Hermes Agent instead of continuing as a
standalone competing platform.

## What happens to this code

- This repository is archived as-is: functional, documented, tested, and
  frozen. It is not deleted, because a working reference is more useful
  than a deleted one, and because the audit process and its findings
  (`AUDIT_REPORT.md`) are worth keeping as a record of what "AI-assisted
  development gone wrong, then corrected for real" actually looks like in
  practice.
- No further feature development, bug fixes, or dependency updates should
  be expected here going forward.
- The AI Company harness (the separate n8n multi-agent planning system)
  is being ported to Hermes's own plugin/hook system in the same move —
  see that package's own README for its current status.
- If you found this repo useful as a reference for VRM avatar rendering,
  viseme-accurate lipsync scheduling, or a voice/wake-word pipeline
  architecture, that part of the code is exactly what's being reused
  going forward — just wrapped around a different, more capable brain.
