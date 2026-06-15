# Contributing

## Development Setup

```bash
pip install -r requirements.txt
pip install pytest pytest-asyncio
```

## Running Tests

Run all tests:
```bash
pytest backend/tests/ -v
```

Run a specific test file:
```bash
pytest backend/tests/test_voice_pipeline.py -v
```

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
