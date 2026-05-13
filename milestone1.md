# Milestone 1: Project skeleton, SQLite, repository, run lock

**Scope:** Establish the Python package, persistent state in SQLite, and a single-writer guard so later milestones can add Gmail ingestion, parsing, and agents without redesigning storage.

**Current repo pointers:** `pyproject.toml`, `app/storage/db.py`, `app/storage/repository.py`, `app/storage/run_lock.py`, `app/models/email.py`, `app/models/digest.py`.

---

## Deliverables

### 1. Installable package

- **`pyproject.toml`** — `daily-knowledge-digest`, runtime deps (e.g. Pydantic, BeautifulSoup, Jinja2 as added over time), optional **`[dev]`** / **`[gmail]`** extras.
- **`app/`** as the main package namespace; tests live under **`tests/`** with **`pythonpath = ["."]`** for imports.

### 2. SQLite schema (`app/storage/db.py`)

Tables created idempotently via **`init_schema`**:

| Table | Role |
|-------|------|
| **`emails`** | Inbound messages: `message_id` (unique), `subject`, `sender`, `body_preview`, `status`, `retry_count`, `error_message`, `received_at`, timestamps. |
| **`agent_outputs`** | Structured JSON payloads keyed by `(email_id, kind)` for routing and processors. |
| **`digests`** | Digest runs: `status`, `title`, `body_html`, `error_message`, timestamps. |
| **`digest_emails`** | Many-to-many linking digests to contributing `email_id`s. |
| **`run_locks`** | Advisory lock row: `lock_name`, `locked_at`, `expires_at`, `owner`. |

**Migrations (additive):** Older databases are upgraded at open time (e.g. **`sender`** column on **`emails`**, **`digests.body_html`** / **`error_message`** where legacy columns existed). New installs use the canonical **`_SCHEMA`** text.

Connection defaults: **`row_factory = sqlite3.Row`**, **`foreign_keys = ON`**, WAL journal where configured.

### 3. `StateRepository`

- Owns a DB connection opened via **`open_initialized(db_path)`**.
- Core operations used across the pipeline:
  - **`upsert_email(EmailInput)`** — insert/update by `message_id`; conflict path resets retry/error fields when re-queued.
  - **`save_agent_output`**, **`create_digest`**, **`attach_email_to_digest`**
  - **`update_email_status`**, **`update_digest_status`**, **`update_digest_body`**
  - Queries: **`fetch_unprocessed_emails`**, **`fetch_retryable_errors`**, **`get_outputs_by_email_ids`**, **`get_email_subject_by_id`**, **`get_email_sender_by_id`**, **`try_reuse_complete_outputs`**, **`fetch_latest_digest_for_utc_calendar_day`**, etc.

Exact method set expanded in Milestones 5–6; M1 establishes the **repository pattern** and **email/output persistence**.

### 4. Pydantic models

- **`EmailInput`** — `message_id`, optional `subject`, **`sender`**, `body_preview`, `received_at`.
- **`ProcessedEmail`** — pipeline-facing view (`id`, `message_id`, `status`, `digest_id`, retry fields).
- **`DigestRecord`** — persisted digest row shape for previews/reporting.

### 5. `RunLock` (`app/storage/run_lock.py`)

- **`acquire(owner=None) -> bool`** — inserts/updates **`run_locks`** when no active holder or prior lock expired (TTL).
- **`release()`** — deletes the row **only if this instance acquired** (token match on `locked_at`); **no-op** if never acquired or token stale — prevents clearing another process’s lock.

### 6. Tests

- Repository behavior with temporary SQLite files (upsert, outputs, digest linkage).
- Run lock: second acquirer blocked while lock valid; release semantics.

---

## Explicitly out of scope for M1

- Live Gmail API usage (Milestone 2).
- HTML parsing / `ParsedHtmlResult` (Milestone 3).
- LLM routing and agents (Milestone 4).
- `DailyDigestAgent`, composer, CLI orchestration (Milestones 5–6).

---

## Acceptance criteria (retroactive)

1. **`python -m pytest`** can run repository and run-lock tests without network or secrets.
2. Schema initialization is **idempotent** and tolerates **existing DB files** via small migrations.
3. Only one automated **`run-daily`**-class writer should hold the advisory lock at a time under normal TTL semantics.
