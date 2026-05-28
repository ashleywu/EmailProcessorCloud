# Daily Knowledge Digest

- **Milestone 1**: project skeleton, configuration, Pydantic models, SQLite storage, `StateRepository`, run lock.
- **Milestone 2**: Gmail integration layer (`app/gmail/`) — `GmailClient`, `GmailFetcher`, `GmailLabeler`, `GmailSender`. Use `build_gmail_client(load_settings())` so OAuth paths stay centralized. All collaborators are mockable; tests run without network or real credentials.
- **Milestone 3–5**: parsing (including **DOM sections** capped/merged via `normalize_sections_for_routing`), LLM **`RouterAgent` + section-scoped processors** (`run_section`), **`DailyDigestAgent`**, **`DigestComposer`**, quality gate (see **`milestone5.md`**); section invariants + **testing guidance for mocks** → **`docs/section-extraction.md`**.
- **Milestone 6**: CLI (`run-daily`, `preview-digest`, `show-config`), `pydantic-settings` loading, end-to-end docs (see `milestone6.md`).
- **Milestone 7**: VPS deployment (`scripts/run-daily.sh`, `docs/deploy-vps.md` — checklist `milestone7.md`).

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

## Troubleshooting: a newsletter never shows up / is “never processed”

There is **no sender-specific blacklist** in code: if something disappears, Gmail ingest usually filtered it **before** SQLite.

Check in order:

1. **`NEWSLETTER_SENDERS`** must include that sender (`show-config` prints the literal list and a **`gmail_messages_list_query_preview`** — paste that string into Gmail’s search box to verify hits). Optionally use **`@publisher.com`** (leading `@`) as domain shorthand when the ESP rotates subdomains; see **`NEWSLETTER_SENDERS`** in `.env.example` and **`build_query`** / **`_sender_search_fragment`** in `app/gmail/fetcher.py`.
2. **`GMAIL_LOOKBACK_DAYS`** — mails **older than** the sliding `after:<epoch>` window are **never listed** again; widen lookback briefly or manually re-touch the mail so it falls in-window.
3. **Labels** `-label:AI_DIGEST_PROCESSED` — if a message already has that label from a prior run, it **will not appear** in the ingest query until you remove it.
4. **Spam** — **`includeSpamTrash` is false**; newsletters in Spam/Trash are skipped.
5. **Empty sender list** — `run-daily` prints a **stderr WARNING** when `NEWSLETTER_SENDERS` is unset; ingest returns nothing useful.

Open the problematic message → **Show original** / headers and paste the **`From:`** line into **`NEWSLETTER_SENDERS`**.

## Scheduled daily run (Windows)

To run **`run-daily`** automatically every day at **5:00 PM** (your PC’s local clock) without opening a terminal:

1. Install the app and Gmail extras in a **`.venv`** under this repo (recommended): `pip install -e ".[dev,gmail]"`.
2. Ensure **`.env`** and Gmail **`credentials.json` / `token.json`** paths work when the repo folder is the working directory (defaults use `Path.cwd()` unless you set absolute paths in `.env`).
3. In **PowerShell**, from the repo root, register the task (one-time):

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\register-daily-task.ps1
   ```

   Default is **17:00** local time. Override: `.\scripts\register-daily-task.ps1 -DailyAt "17:00"`.

4. Logs append under **`logs/run-daily-YYYY-MM.log`**.

Remove the task later: **Task Scheduler** → **Task Scheduler Library** → **DailyKnowledgeDigest** → **Delete**, or:

```powershell
Unregister-ScheduledTask -TaskName DailyKnowledgeDigest -Confirm:$false
```

The task runs **in your Windows user context** (typical when creating tasks without “run whether user is logged on”). If you need it while logged off, configure **Run whether user is logged on or not** and stored credentials in Task Scheduler.

## Scheduled daily run (Ubuntu VPS)

Lightsail-style flow: **`ubuntu`** user, layout under **`~/daily-digest/`**, invoking **`scripts/run-daily.sh`** from **`cron`**. On a typical UTC VPS, **`0 17 * * *`** runs at **17:00 UTC** (~**10:00 AM Pacific** during PDT) — full steps live in [`docs/deploy-vps.md`](docs/deploy-vps.md).

## Tests

```bash
python -m pytest
```

Tests use fakes and mocks (`GmailClient(service_factory=...)`, patched Gmail in CLI tests where needed). No real credentials required.

Digest/orchestration coverage includes **`tests/test_milestone5_daily_digest.py`** (send/QA/run-lock/skips); **`tests/test_step5_section_digest_integration.py`** (section routing: mock **`RouterAgent.run`** from stable keys such as **`section_heading`** — never list-queue **`side_effect` across retries** when a failing run skips later sections; details in **`docs/section-extraction.md`** § *Testing section routing across retries*); repository/compose helpers under **`tests/test_repository_sections.py`**, **`tests/test_step3_section_digest.py`**, **`tests/test_composer_*.py`**, etc.

## Development milestone workflow

Implement milestone specs in order (`milestone5.md`, `milestone6.md`, **`milestone7.md`**). Each milestone adds tests and keeps CLI/storage contracts explicit where applicable (Milestone 7 is deployment documentation + shell wrapper).

## Safety guarantees

- Digest send failures or quality-gate failures do **not** archive source mail (see `DailyDigestAgent`).
- **`preview-digest`** only reads the database; it does not modify Gmail or send email.
- **`run_lock`** prevents overlapping **`run-daily`** runs; lock contention exits non-zero from the CLI.
- **`show-config`** never prints raw API keys or token/credential file contents.
- Re-running **`run-daily`** is idempotent for routing: pending mail and retryable failures are merged automatically (no separate “retry” command).
