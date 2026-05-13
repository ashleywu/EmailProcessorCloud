# Milestone 2: Gmail integration layer

**Scope:** Encapsulate Gmail API usage behind small, testable components: list/fetch messages, extract HTML for parsing, OAuth token handling, send HTML mail, and apply pipeline labels (processed / error) plus archive.

**Prerequisite:** Milestone 1 (repository can persist `EmailInput` rows).

**Current repo pointers:** `app/gmail/client.py`, `app/gmail/fetcher.py`, `app/gmail/sender.py`, `app/gmail/labeler.py`, `tests/fakes/gmail.py`.

---

## Deliverables

### 1. `GmailClient`

- Builds or injects an authenticated **`googleapiclient`** service from disk paths (**`credentials.json`**, **`token.json`**).
- Uses **`google_auth_oauthlib.flow.InstalledAppFlow`** (or equivalent) for first-time OAuth; persists refresh token for unattended runs.
- **`execute(callable)`** (or similar) — thin wrapper so tests can substitute **`FakeGmailService`** without importing Google libraries in unit tests that don’t need them.

### 2. `GmailFetcher`

- **`build_query(senders, lookback_days, exclude_labels, …)`** — Gmail search string: OR’d **`from:`** clauses, **`after:<epoch>`** for deterministic window, excludes **`AI_DIGEST_PROCESSED`** / **`AI_DIGEST_ERROR`** labels by default.
- **`fetch_recent()`** — lists message IDs, then **`messages.get`** with **`format="metadata"`** and headers **`From`**, **`Subject`**, **`Date`** for lightweight rows.
- **`fetch_message_html(message_id)`** — **`format="full"`**, returns HTML via **`extract_html_from_gmail_payload`** (walk parts; wrap plain text in minimal HTML if needed).

### 3. `GmailMessage` and parsing

- **`parse_gmail_message(api_payload) -> GmailMessage`**: `message_id`, `thread_id`, **`sender`** (From header), `subject`, `snippet`, `received_at`, `label_ids`.
- **`to_email_input() -> EmailInput`**: maps into Milestone 1 model including **`sender`** (stripped; empty → `None`).

### 4. `GmailLabeler`

- Resolves label IDs by **name** (create if missing as required by product).
- **`mark_processed`**, **`archive`**, error/processed label helpers used after successful digest send (exact sequence finalized in Milestone 5).

### 5. `GmailSender`

- **`send_html(to, subject, html)`** — RFC5322 delivery via Gmail API for the assembled digest.

### 6. Test doubles

- **`tests/fakes/FakeGmailService`** — records calls; serves canned **`messages.list`** / **`messages.get`** payloads.
- **`make_message(...)`** helper builds metadata payloads with **`From`** / **`Subject`** headers for fetcher/parser tests.

---

## Explicitly out of scope for M2

- Newsletter HTML semantic parsing (**Milestone 3**).
- Router/processor LLM calls (**Milestone 4**).
- **`DailyDigestAgent`** wiring (**Milestone 5**).

---

## Acceptance criteria (retroactive)

1. Fetcher unit tests run **without** real Google credentials using fakes.
2. **`parse_gmail_message` + `to_email_input`** preserves **`From`** into **`EmailInput.sender`** for repository upserts.
3. Optional dependency **`[gmail]`** installs **`google-api-python-client`**, **`google-auth`**, **`google-auth-oauthlib`** so **`run-daily`** can execute on a configured workstation.
