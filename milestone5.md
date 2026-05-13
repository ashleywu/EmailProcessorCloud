# Milestone 5: DailyDigestAgent orchestration, digest composition, quality gate

**Prerequisite:** Milestones 1–4 are complete. Before implementing, read: `app/storage/repository.py`, `app/storage/run_lock.py`, `app/storage/db.py`, `app/gmail/sender.py`, `app/gmail/labeler.py`, `app/agents/router_agent.py`, `app/models/outputs.py`, `app/models/digest.py`.

---

## I. Core prerequisites (must be done first)

### 1. Schema and DB

- Rename **`digests.body_markdown`** to **`body_html`** (still TEXT, storing HTML).
- Add **`error_message`** to **`digests`** and to Pydantic models such as **`DigestRecord`** (`str | None`).
- **`emails.status` convention:** stay aligned with **`StateRepository`** queries—use **lowercase** strings: **`'pending'`**, **`'failed'`**, **`'archived'`** (use lowercase for the archived state introduced in this milestone). Specs and tests must not use uppercase literals such as **`FAILED`** / **`ARCHIVED`** if they disagree with the DB.
- **Existing SQLite files:** dev/deploy DBs may already exist. Beyond updating **`_SCHEMA`**, define an explicit strategy (e.g. detect column names at startup: if **`body_markdown`** exists then **`ALTER TABLE RENAME COLUMN`**, or a one-off migration script) so behavior is not “new DBs only.”

### 2. `StateRepository` extensions

- **`update_digest_body(digest_id, *, body_html, title=None)`** (or equivalent): overwrite body during quality-gate retries; if only body and **`updated_at`** change, behavior should match **`update_digest_status`** conventions (timestamps, etc.).
- **`get_outputs_by_email_ids(email_ids: Sequence[int]) -> ...`** contract:
  - Returns everything needed to compose a digest: at least **`email_id`**, **`kind`**, **`payload`** (and optionally **`created_at`** / **`id`** for troubleshooting).
  - **Multiple rows per `(email_id, kind)`:** consume **only the latest row by `created_at` (or `id`)**, or aggregate inside this method so there is **at most one row per email per `kind`**; the rule must be fixed in the docstring—the **Composer must not resolve ambiguity itself**.
- **`create_digest`:** parameters and INSERT columns align with **`body_html`**; remove references to **`body_markdown`**.

### 3. Safe `RunLock` release

- **Goal:** A flow that never successfully **`acquire()`** on this instance **must not delete another instance’s lock** from **`finally`**.
- **Implementation:** Prefer tracking inside **`RunLock`** whether this instance acquired (or validate owner/token on **`release()`**); document that **`release()`** without **`acquire()`** is a **no-op or raises**—no unconditional **`DELETE`**.
- If the caller uses a boolean flag, **`DailyDigestAgent`** must enforce a single path; still prefer **`RunLock`**-level guards against future misuse.

### 4. Per-email failure (do not block the batch)

- When **one** message fails at **parse / route / processor**:
  - Set **`emails.status`** to **`'failed'`**;
  - Use **`update_email_status(..., increment_retry=True)`** (or equivalent consistent with **`fetch_retryable_errors`**) to bump **`retry_count`** so messages under the cap can be picked up later;
  - **Skip** that message and continue with the rest.
- **The digest includes only successfully processed messages with valid structured outputs**; only those participate in **`digest_emails`** and Gmail archive/labeling **after send succeeds**.

### 5. Package layout

- Orchestration entry point: **`app/agents/daily_digest_agent.py`** (same **`app/agents/`** tree; **do not** use **`app/agent/`**).

### 6. New directory layout

```
app/digest/
  composer.py
  quality_gate.py
  templates/
    daily_digest.html.j2
app/agents/
  daily_digest_agent.py
```

---

## II. Milestone 5 functional requirements

### 1. `DailyDigestAgent.run_daily()` orchestration

1. **Acquire run lock:** if **`acquire()`** fails, **exit safely** (no digest row writes, no mail mutations, no send; **do not call `release()`**).
2. **Candidate messages:** merge **`fetch_unprocessed_emails()`** (**`pending`**) and **`fetch_retryable_errors()`** (**`failed`** under retry cap); dedupe by **`email_id`**.
3. For each candidate: **parse → route → matching processor**; apply §I.4 on failure.
4. Each success: **`save_agent_output`** (and persist router output if that’s the architecture); **`attach_email_to_digest(digest_id, email_id)`** only for messages that will appear in this digest (you may **`create_digest(status='draft', …)`** first or accumulate successes then create—implementation choice, but links must stay consistent).
5. **Empty success set:** if **no** message produces composable output:
   - **Do not** send;
   - **Do not** archive / **`AI_DIGEST_PROCESSED`** / category labels for any message;
   - Optionally create a **`digests`** row marked **`skipped`** or **`empty`** (name must match code/constants/docs) or **omit** creating a digest—**pick one and document it in code or comments**; tests must cover the branch.
6. **`DigestComposer`:** depends only on **`get_outputs_by_email_ids`** (plus metadata such as **subject** / **sender** if not embedded in payloads—no full-body reread), renders **HTML** with **Jinja2** (template language for UI copy may be English by default). Section titles map from **`RouteCategory`**:

   | `RouteCategory` | Section title        |
   |-----------------|----------------------|
   | TECHNOLOGY      | Technical Index      |
   | RADAR           | AI Radar             |
   | LEADERSHIP      | Leadership Signals   |
   | NOISE           | Filtered Noise       |

7. **Quality gate:** **`DigestQualityGateAgent`** inspects HTML (garbled output, suspicious unescaped markup, broken structure, etc.). **Retry semantics:** **first draft + up to 2 rewrites driven by `problems` = at most 3 generations**; if the third still fails, raise **`QualityGateFailedException`** (or the project’s chosen exception).
8. **Send:** after the gate passes, **`GmailSender.send_html`**.
9. **Only after send succeeds** (for messages **included in this digest**):
   - **`GmailLabeler.add_category(message_id, category)`**;
   - **`GmailLabeler.mark_processed(message_id)`** (**`AI_DIGEST_PROCESSED`**);
   - **`GmailLabeler.archive(message_id)`**;
   - DB: set **`emails.status`** to **`'archived'`** (§I.1).
10. **`finally`:** call **`release()`** only if this run **successfully `acquire()`’d**.

### 2. Digest status when send fails

- **Send throws or returns invalid:** **do not** archive, **do not** apply **`AI_DIGEST_PROCESSED`**, **do not** apply category labels.
- **Persistence:** set **`digests.status`** to a distinguishable value (e.g. **`'send_failed'`** vs **`'error'`**—choose one scheme and fix it in **`DigestRecord`** / constants); record a short reason in **`error_message`**; keep **`body_html`** as the last good HTML. Tests must cover “send failure ⇒ no archive.”

### 3. Quality-gate failure (`QualityGateFailedException`)

- **Do not** send the digest;
- **Do not** archive source messages;
- **Do not** apply **`AI_DIGEST_PROCESSED`** (or category labels for this digest);
- Set **`digests.status`** to **`'error'`** (or unify with §II.2 but distinguish QA vs send in **`error_message`** if needed);
- Persist the **last failing `body_html` draft** and **`error_message`** (include QA **`problems`** summary or last gate text).

### 4. `DigestComposer`

- Uses only repository structured outputs—**does not** reread full raw mail.
- Output is **HTML** (**`app/digest/templates/daily_digest.html.j2`**; section labels come from template / **`DigestComposer`** / **`DailyDigestAgent`** parameters).
- After QA failure, accept **`problems: list[str]`** (or agreed type) and emit revised HTML (**`DailyDigestAgent`** drives the loop).

### 5. `DigestQualityGateAgent`

- **Recommended:** mostly **deterministic rules** (parse HTML, length, suspicious fragments, unclosed tags) for stable tests; if an LLM assists, **stub it in tests** to avoid flakiness.
- Return shape: **`pass: bool`**, **`problems: list[str]`** (non-empty when failing).

---

## III. Required tests

1. **No `archive` on source messages before send succeeds.**
2. **Send failure:** no **`archive`** (and no processed labeling), consistent with §II.2.
3. **Quality gate:** after **more than 3** compose attempts, **`digests.status`**, **`error_message`**, and **`body_html`** persistence match §II.3.
4. **Run lock:** an instance that **did not** acquire must **not** clear another holder’s **`run_locks`** row.
5. **Single-email failure:** one **`'failed'`** message does **not** prevent other successes from entering the same digest (assert HTML / links only include successes).
6. **(Recommended)** **`digest_emails`:** after send, successful **`email_id`** rows link to the correct **`digest_id`**.

---

## IV. Reference files (implementation checklist)

- **`app/gmail/labeler.py`:** **`PROCESSED_LABEL`**, **`category_label_name`**, **`archive`** semantics.
- **`app/gmail/sender.py`:** what counts as send success.
- **`app/models/outputs.py`:** **`RouteCategory`** and **`*Output`** models (Composer deserializes **`payload`**).
- **`app/storage/repository.py`:** **`fetch_unprocessed_emails`** / **`fetch_retryable_errors`** / **`attach_email_to_digest`** / **`update_email_status`**.

---

**This document is the single source of requirements for Milestone 5.** If local code disagrees, align implementation and tests with this spec and existing DB/query conventions.
