# Contributing

## Development Setup

```bash
pip install -r requirements.txt
pip install pytest pytest-asyncio
npm install
```

## Running Tests

Backend (Python):
```bash
pytest backend/tests/ -v
pytest tests/cli/ -v
```

Run a specific backend test file:
```bash
pytest backend/tests/test_voice_pipeline.py -v
```

Frontend (JavaScript):
```bash
npm run test:frontend
```

Voice-pipeline tests need the heavier `requirements-voice.txt` set
(faster-whisper, sounddevice, webrtcvad) plus `ffmpeg`/`libportaudio2`
system libraries — see `.github/workflows/ci.yml` for the exact setup.

## Code Style

- Python: no strict style guide, but keep files under 800 lines
- JavaScript: modern ES modules, no bundler
- Imports: standard lib → third-party → local (alphabetical groups)

## Adding a Skill

Create a new `.py` file in `backend/skills/` with any exported functions.
Skills are auto-discovered at startup.

## Making Changes

1. Create a branch
2. Make your changes
3. Run the tests: `pytest backend/tests/ -v`
4. Open a pull request

## Commit Messages

Write concise commit messages in present tense describing what and why:
- `fix: resolve avatar emotion reset on VRM load`
- `feat: add FTS5 full-text search across all sessions`
- `refactor: split memory.py into manager/hybrid/fts modules`
