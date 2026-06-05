# Milestone 6: CLI, one-shot run-daily, preview, configuration, end-to-end tests

**Prerequisite:** Milestones 1–5 are complete. Orchestration lives in **`DailyDigestAgent`** under **`app/agents/daily_digest_agent.py`** (**do not** use **`app/agent/`**).

Before implementing, read: `app/main.py`, `app/config.py`, `app/gmail/fetcher.py`, `app/storage/repository.py`, `app/agents/daily_digest_agent.py`.

---

## I. Design principles

### 1. Idempotent, minimal CLI

- **Do not** ship separate **`ingestion`** / **`retry`** subcommands.
- **Scheduled or manual** runs use **`run-daily` only:** **`DailyDigestAgent`** already merges **`fetch_unprocessed_emails`** and **`fetch_retryable_errors`**; repeating **`run-daily`** means “fetch new mail + retry failures under the cap” without a second command.
- **Do not** add **`retry-errors`** (or any duplicate “retry-only” command).

### 2. Single source of truth (`Settings` + validation)

- **All** runtime config (LLM, Gmail, digest recipient, lock, DB, quality attempts, etc.) flows through **`config.Settings`** (or one equivalent settings type), loaded and validated **once** at startup.
- **Must use** **`pydantic-settings`** (**`BaseSettings`**) from env / **`.env`** with typed **`Field`** constraints; migrate any ad-hoc **`load_settings()`** into that model while keeping **`load_settings()`** as the public entry point.
- **Forbidden:** scattered **`os.getenv("OPENAI_API_KEY")`** (and similar) inside **`app/`**, **`OpenAIProvider`**, **`DailyDigestAgent`**, etc.—inject a **`Settings`** instance (constructor or factory).
- **Tests:** prefer constructing **fake/minimal `Settings`**; avoid **`monkeypatch`** on global env except for tests that specifically validate env loading.
- **`.env.example` and README** variable names must match **`Settings`** env aliases—no duplicate aliases.

---

## II. Settings loading and fail-fast

### 1. `DIGEST_RECIPIENT_EMAIL`

- **`run-daily`:** if the recipient is **missing or empty**, **fail immediately** at the **earliest** pipeline stage (**before** Gmail fetch, **`run_daily()`**, or network I/O), non-zero exit, clear stderr message.
- Prefer **`Settings`** marking the field **required** (Pydantic); CLI may catch validation errors and print a friendly line.

### 2. Other validation

- **`DAILY_DIGEST_MAX_QUALITY_GATE_ATTEMPTS`:** reject **≤ 0** at **`Settings`** level (e.g. **`Field(ge=1)`**); invalid integers fail load.

---

## III. `python -m app.main show-config` (long-lived + redacted)

### 1. Role

- **`show-config`** stays permanently for Cron/cloud debugging (**environment isolation, paths, model names, scopes**).
- **Never** print plaintext **API keys, access tokens, refresh tokens, client secrets**, or the **contents** of **`token.json`** / **`credentials.json`**.

### 2. Redaction rules (implement + test)

- **Secret-like strings** (e.g. **`OPENAI_API_KEY`**): emit **masked** output—keep a recognizable prefix such as **`sk-proj-`**, replace the rest with **`******`** (or fixed-length stars); very short values → **`***`**.
- **Paths:** printing **`GMAIL_CREDENTIALS_PATH`**, **`GMAIL_TOKEN_PATH`**, etc. is OK (paths are not secrets); **do not** **`open()`** those files and dump contents.
- **Gmail summary** (label names, scopes, **count** of newsletter senders, etc.): **metadata only**; future fields that might contain secrets default to redaction.
- **Self-check:** tests assert **`show-config` stdout** does **not** contain a full real API key substring (use a fixture key).

---

## IV. `python -m app.main run-daily`

### 1. Required end-to-end order

These three steps run in **one** invocation (thin wrapper in **`app/main.py`** is fine; user runs nothing beforehand). After **`Settings`** validates and **`DIGEST_RECIPIENT_EMAIL`** is set:

1. Build **`GmailClient`** / **`GmailFetcher`** from **`Settings`** (**`senders`** ← **`NEWSLETTER_SENDERS`**, **`lookback_days`** ← **`GMAIL_LOOKBACK_DAYS`**, etc.).
2. **`fetcher.fetch_recent()`** → for each **`GmailMessage`**, **`StateRepository.upsert_email(msg.to_email_input())`**.
3. Construct **`DailyDigestAgent`** (repo, lock, fetcher, router/processors, composer, quality gate, labeler, sender; **`digest_to`** ← **`Settings.digest_recipient_email`**; LLM from **`Settings`**) and call **`run_daily()`**.

**Note:** if **`NEWSLETTER_SENDERS`** is empty, **`fetch_recent`** matches existing **`GmailFetcher`** behavior (empty list); README should say effective **`run-daily`** needs configured senders.

### 2. `DailyDigestAgent.run_daily()` boundary

- **`run_daily()`** may omit **`fetch_recent`** internally (easier unit tests for “DB candidates only”); **Gmail → SQLite sync** belongs in the **`run-daily`** CLI entry.
- Existing **`run_daily()`** semantics (lock, merged candidates, per-email failure, QA loop, send, post-send archive, etc.) stay unless this doc says otherwise.

### 3. Run lock and CLI exit codes

If **`RunLock.acquire()`** fails so orchestration never runs: **`run-daily`** must exit **non-zero** and print a short stderr note (e.g. another instance holds the lock) so Cron/scripts detect failure—**not** exit **0**.

---

## V. `python -m app.main preview-digest --date YYYY-MM-DD`

### 1. Behavior

- Read **`body_html`** from SQLite **`digests`**.
- **Date semantics:** **`YYYY-MM-DD`** is a **UTC calendar day** (same convention as digest titles).
- **Selection:** among digests whose **`created_at`** falls on that UTC day, pick the row with the **latest `created_at`**—**output only that row**. If the day has **no** digest: exit non-zero with a clear message.
- **Output:** default HTML to **stdout**; optional flag writes the same HTML to a file (name in **`--help`**).
- **Forbidden:** send mail, Gmail mutating APIs, or updating **`emails` / `digests`** state (read-only queries only).
- **Failure paths:** expected failures (no digest for the day, §V.2 empty body, etc.) must be handled **inside **`preview-digest`**: **stderr + non-zero exit**—**do not** surface raw tracebacks to users.

### 2. `body_html` is `NULL` or blank (decision)

After selecting the latest digest for that UTC day, if **`body_html`** is SQL **`NULL`** or **whitespace-only** (e.g. **`draft`**, interrupted write, **`error_message`**-only row):

- Treat as **failure:** **non-zero exit** (e.g. **`sys.exit(1)`**) so Cron/scripts/CI detect it.
- Print a **short stderr** explanation (include **`digest_id`**, **`status`** if available)—**no** uncaught-exception traceback to the user (catch internally if needed).
- **Stdout:** **do not** emit real HTML; if **`--output`** was passed, **do not** leave a misleading “successful” file (implementation chooses: skip file creation or write nothing useful—document in **`--help`** like other failures).
- **Docs layering:** README covers **basic **`preview-digest`** usage** only; edge behavior lives in **§V + `--help`** (**`--help`** must mention failures for **no digest** / **no previewable body**).

### 3. `StateRepository`

- Add a query (name your choice; document UTC-day + “latest row” rules) for **`preview-digest`**.

### 4. Config vs **`run-daily`**

**`preview-digest`** needs only a resolvable **DB path** (**`DAILY_DIGEST_DB_PATH`** or default **`Settings.db_path`**); **must not** require **`OPENAI_API_KEY`**, **`DIGEST_RECIPIENT_EMAIL`**, or other **`run-daily`-only** fields. Implementation: load **`Settings`** then **skip** run-daily-required validation for this subcommand (still validate date args and DB readability). Same **`Settings` / `.env`** source—no second env vocabulary.

---

## VI. Quality attempts: env var and refactor

- Replace hard-coded **`DailyDigestAgent._MAX_QUALITY_ATTEMPTS = 3`** with **`Settings`**.
- **Env name:** **`DAILY_DIGEST_MAX_QUALITY_GATE_ATTEMPTS`** (default **`3`**).
- **Semantics:** **at most N “compose → quality gate” rounds** (**including** the first draft). Document on **`Settings`** to avoid confusion with “extra retries only.”

---

## VII. `.env.example`

Keep in sync with **`Settings`** (Pydantic env aliases), including at least:

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI key (**required for `run-daily`**; **not for `preview-digest`**) |
| `ROUTER_MODEL` | Router model |
| `PROCESSOR_MODEL` | Processor model |
| `DIGEST_RECIPIENT_EMAIL` | Digest recipient (**required / fail-fast for `run-daily`**; **not for `preview-digest`**) |
| `NEWSLETTER_SENDERS` | Comma-separated sender filters for fetch query |
| `GMAIL_CREDENTIALS_PATH` | OAuth client secrets JSON |
| `GMAIL_TOKEN_PATH` | Token cache path |
| `GMAIL_LOOKBACK_DAYS` | Fetch window (days) |
| `DAILY_DIGEST_DB_PATH` | SQLite path (optional; has default) |
| `DAILY_DIGEST_LOCK_NAME` | Lock name (optional) |
| `DAILY_DIGEST_LOCK_TTL_MINUTES` | Lock TTL |
| `DAILY_DIGEST_MAX_EMAIL_RETRIES` | Email failure retry cap (aligned with **`fetch_retryable_errors`**) |
| `DAILY_DIGEST_MAX_QUALITY_GATE_ATTEMPTS` | Max QA rounds (§VI) |

**Do not** document env vars the code never reads (e.g. a stray **`RUN_LOCK_TTL_MINUTES`**). If **`DigestComposer`** has **no** LLM and nothing reads **`COMPOSER_MODEL`**, **omit** it from **`.env.example`**.

**Dependency:** **`pydantic-settings`** belongs in core **`pyproject.toml`** dependencies (not optional).

---

## VIII. `README.md`

Update or add:

1. **Setup:** venv, editable install, **`pip install -e ".[dev]"`** / **`pip install -e ".[dev,gmail]"`**; config via **`.env`** and **`Settings`** validation.
2. **Gmail OAuth:** required scopes or point to **`python -m app.main show-config`** for paths, labels, scopes (**redacted**).
3. **Commands:** **`run-daily`**, **`preview-digest`**, **`show-config`** (keep **`show-config`**). **`preview-digest`** in README: **basic usage only**; boundary semantics (**no digest for day**, **empty body**, exit codes) stay in **§V** and **`--help`** (**`--help`** must summarize “no record / no body” ⇒ failure + non-zero exit).
4. **Milestone workflow:** one–two lines per M1–M6 boundary.
5. **Safety:** no archive on send failure / QA failure; **`preview-digest`** read-only; **`run_lock`** prevents overlapping **`run-daily`**; idempotent **`run-daily`**; **`show-config`** never prints raw secrets.

---

## IX. Test requirements

1. **End-to-end dry run** (pytest, no real network): mock Gmail (existing fake pattern); mock LLM via injected **`Settings`** / fake client (**avoid** relying on **`OPENAI_API_KEY`** monkeypatch); mock or assert **`GmailSender`** does not really send.
2. Assert **fetch → upsert → `run_daily`** yields expected digest (or acceptable empty/skipped); **labels/archive only after send success**.
3. **`RunLock`** behavior including **no accidental release of another holder’s lock**.
4. **`preview-digest`:** for multiple digests on the same UTC day, only the **latest `created_at`** body is emitted; **empty / NULL `body_html`** ⇒ **non-zero exit**, **stderr message**, **no** uncaught traceback (§V.2); **no digest for day** ⇒ same (§V.1).
5. **`show-config`:** stdout **does not** contain unredacted secrets (§III).
6. **`run-daily`** without recipient ⇒ **fail-fast** (**Settings** or CLI).
7. Remove or avoid tests/docs for deprecated **`retry-errors`**.
8. **`DailyDigestAgent` section mocks:** deterministic **`RouterAgent.run`** stubs for retries — **avoid list `side_effect` queues** — covered in **`tests/test_step5_section_digest_integration.py`**.

---

## X. Forward reference: content-unit routing (Phase 6)

Planned routing refactor (**Milestone 8**): `docs/content-unit-routing-design.md`, `docs/content-unit-classifiers.md`, `milestone8-content-unit-routing.md`. Does not change Milestone 6 deliverables.

---

## X. Delivery checklist (self-review)

- [ ] **`Settings`:** **`pydantic-settings`** only; **no scattered `os.getenv` for secrets**.
- [ ] **`python -m app.main run-daily`:** after validation, **Gmail fetch → `upsert_email` → `DailyDigestAgent.run_daily()`**; **missing `DIGEST_RECIPIENT_EMAIL` ⇒ immediate failure**.
- [ ] **`python -m app.main preview-digest --date YYYY-MM-DD`:** latest digest HTML for that UTC day → stdout or file; no send, no Gmail writes; **empty/`NULL` body or no digest for day** ⇒ **non-zero + stderr**, **no traceback** (§V.1–§V.2); **`--help`** summarizes failures; README basic usage only (§VIII).
- [ ] **`python -m app.main show-config`:** retained; redacted secrets; never dumps credential file bodies.
- [ ] **`DAILY_DIGEST_MAX_QUALITY_GATE_ATTEMPTS`** wired through **`Settings`** and **`DailyDigestAgent`**.
- [ ] **`.env.example`**, **`README.md`** match **`Settings`**.
- [ ] Tests above pass.

---

**This document is the single source of requirements for Milestone 6.** If code diverges, reconcile toward this spec and existing DB/state conventions.
