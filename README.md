# Daily Knowledge Digest

- **Milestone 1**: project skeleton, configuration, Pydantic models, SQLite storage, `StateRepository`, run lock.
- **Milestone 2**: Gmail integration layer (`app/gmail/`) — `GmailClient`, `GmailFetcher`, `GmailLabeler`, `GmailSender`. Use `build_gmail_client(load_settings())` so OAuth paths stay centralized. All collaborators are mockable; tests run without network or real credentials.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[dev]"             # core + tests (no Google libs needed)
pip install -e ".[dev,gmail]"        # add Google API client for live runs
```

Copy `.env.example` to `.env` and adjust paths. For real Gmail runs also drop your OAuth `credentials.json` into the path pointed at by `GMAIL_CREDENTIALS_PATH`; the first run writes a refreshable token to `GMAIL_TOKEN_PATH`.

## Tests

```bash
python -m pytest
```

Tests use injected fake services via `GmailClient(service_factory=...)`, so no Google libraries or credentials are required.

## CLI

```bash
python -m app.main --help
python -m app.main show-config
```

`show-config` prints a safe Gmail configuration summary (paths, scopes, pipeline label names only — no token or credential file contents).
