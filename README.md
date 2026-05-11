# Daily Knowledge Digest

- **Milestone 1**: project skeleton, configuration, Pydantic models, SQLite storage, `StateRepository`, run lock.
- **Milestone 2**: Gmail integration layer (`app/gmail/`) — `GmailClient`, `GmailFetcher`, `GmailLabeler`, `GmailSender`. Use `build_gmail_client(load_settings())` so OAuth paths stay centralized. All collaborators are mockable; tests run without network or real credentials.
- **Milestone 3–5**: parsing, LLM agents, daily digest orchestration, HTML composer, quality gate (see `milestone5.md`).
- **Milestone 6**: CLI (`run-daily`, `preview-digest`, `show-config`), `pydantic-settings` loading, end-to-end docs (see `milestone6.md`).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e ".[dev]"             # core + tests (no Google libs needed)
pip install -e ".[dev,gmail]"        # add Google API client for live Gmail runs
```

Copy `.env.example` to `.env` and adjust paths. Configuration is loaded via **`app.config.Settings`** (`load_settings()` applies `python-dotenv` to `.env` then reads the environment).

For real Gmail runs, put OAuth `credentials.json` at `GMAIL_CREDENTIALS_PATH`; the first run writes a refresh token to `GMAIL_TOKEN_PATH`.

## Gmail OAuth scopes

Run:

```bash
python -m app.main show-config
```

This prints OAuth scopes, pipeline label names, paths, model names, and a **redacted** `OPENAI_API_KEY`. Credential and token JSON files are **never read** for this output.

## CLI

```bash
python -m app.main --help
python -m app.main show-config
python -m app.main run-daily
python -m app.main preview-digest --date YYYY-MM-DD
python -m app.main preview-digest --date YYYY-MM-DD -o preview.html
```

- **`run-daily`**: Loads messages with `GmailFetcher.fetch_recent()`, upserts into SQLite, then runs `DailyDigestAgent.run_daily()`. Requires **`DIGEST_RECIPIENT_EMAIL`** and **`OPENAI_API_KEY`**. Exits with a non-zero code if another instance holds the run lock or if required settings are missing.
- **`preview-digest`**: Read-only: prints the latest digest HTML for the given **UTC** calendar day from SQLite. Does **not** send mail or call Gmail. Details for missing rows or empty HTML are in `--help`; failures use stderr and a non-zero exit code.
- **`show-config`**: Safe summary for Cron/cloud debugging; secrets are masked.

## Tests

```bash
python -m pytest
```

Tests use fakes and mocks (`GmailClient(service_factory=...)`, patched Gmail in CLI tests where needed). No real credentials required.

## Development milestone workflow

Implement milestone specs in order (`milestone5.md`, `milestone6.md`). Each milestone adds tests and keeps CLI/storage contracts explicit.

## Safety guarantees

- Digest send failures or quality-gate failures do **not** archive source mail (see `DailyDigestAgent`).
- **`preview-digest`** only reads the database; it does not modify Gmail or send email.
- **`run_lock`** prevents overlapping **`run-daily`** runs; lock contention exits non-zero from the CLI.
- **`show-config`** never prints raw API keys or token/credential file contents.
- Re-running **`run-daily`** is idempotent for routing: pending mail and retryable failures are merged automatically (no separate “retry” command).
