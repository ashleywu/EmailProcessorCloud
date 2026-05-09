# Daily Knowledge Digest

Milestone 1: project skeleton, configuration, Pydantic models, SQLite storage, `StateRepository`, and run lock.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and adjust paths if needed.

## Tests

```bash
python -m pytest
```

## CLI (placeholder)

```bash
python -m app.main --help
```
