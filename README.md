# Amalgam

A voice-first AI companion with a 3D VRM avatar, MCP tool integration,
multi-provider LLM support, extensible skills, and persistent memory. Runs
locally on your machine.

> ⚠️ **Archived.** Development is discontinued in favor of a
> [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin, which
> already covers the memory/skill/self-learning/scheduling side at scale. This
> repo remains as a working, tested reference.

> 🛠️ **Vibe-coded.** Built with heavy AI assistance; no formal review. The
> feature set below was manually exercised.

## Features

- 3D VRM avatar (lip-sync, emotions, idle)
- Voice chat (TTS / STT)
- Multi-provider LLM + native function calling
- MCP tool servers
- Auto-discovered skill system
- Persistent memory (SQLite + embeddings), FTS5 search
- User profile auto-learning, reflective + planning agents, parallel tool calls
- Cost/metrics tracking, theme system, character system, Vault (markdown)

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

See `LEGACY_NOTICE.md` and `AUDIT_REPORT.md` in-repo for the full rationale and
what was fixed to reach a stable state.

## Known issues / Limitations

- Superseded by Hermes; no further fixes planned.
- Heavy local deps (VRM renderer, embedding model) — setup is non-trivial.

## License

MIT
