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
  - Returns everything needed to compose a digest: at least **`email_id`**, **`kind`**, **`payload`** (and optionally **`created_at`** / **`id`** / **`email_section_id`** for troubleshooting).
  - **Section pipeline:** compose from **multiple rows per `email_id`** distinguished by **`email_section_id`** and **`kind`**. Consume **only the latest row per `(email_id, email_section_id, kind)`** by greatest **`id`** (or equivalent)—the Composer must receive an unambiguous set; **`DigestComposer` itself does not disambiguate duplicates**.
- **`create_digest`:** parameters and INSERT columns align with **`body_html`**; remove references to **`body_markdown`**.

### 3. Safe `RunLock` release

- **Goal:** A flow that never successfully **`acquire()`** on this instance **must not delete another instance’s lock** from **`finally`**.
- **Implementation:** Prefer tracking inside **`RunLock`** whether this instance acquired (or validate owner/token on **`release()`**); document that **`release()`** without **`acquire()`** is a **no-op or raises**—no unconditional **`DELETE`**.
- If the caller uses a boolean flag, **`DailyDigestAgent`** must enforce a single path; still prefer **`RunLock`**-level guards against future misuse.

### 4. Per-email failure (do not block the batch)

- When **one** message fails at **parse / route / processor** (**including**: any thrown error **mid–multi-section slice loop** ⇒ that message **must not `attach_email_to_digest`** for this digest, even when earlier slices already wrote **`agent_outputs`**):
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
3. For each candidate **(§I.4 slice loop is all-or-nothing per digest inclusion):**
   - When **`repo.try_reuse_complete_outputs(email_id)`** succeeds, **`attach_email_to_digest(digest_id, email_id)`** without refetch/process (shortcut when **every** slice already holds router + processor outputs).
   - Else **`fetch_message_html` → `parse_newsletter_html` → `normalize_sections_for_routing` → `replace_email_sections`**, then iterate persisted **`email_sections`** in reading order (**`sorted(..., order_index, id)`**). **`_reuse_section_processor_if_cached`** skips router/processor RPC when router+processor JSON already matches that **`email_sections.id`**. Otherwise **`RouterAgent.run` → `save_agent_output`(router)** → **`run_section`** on the routed processor **`save_agent_output`**. **Only when all slices succeed** ⇒ **`attach_email_to_digest`**; otherwise apply §I.4 (**no attach**—partial SQLite rows remain until rewritten or cascading **`replace`** when slice keys/hashes shift).
4. **Empty success set:** if **no** message produces composable output:
   - **Do not** send;
   - **Do not** archive / **`AI_DIGEST_PROCESSED`** / category labels for any message;
   - Optionally create a **`digests`** row marked **`skipped`** or **`empty`** (name must match code/constants/docs) or **omit** creating a digest—**pick one and document it in code or comments**; tests must cover the branch.
5. **`DigestComposer`:** depends only on **`get_outputs_by_email_ids`** (+ **subject/sender**/section metadata joins—no raw-mail reread), renders HTML with **Jinja2**.

   | `RouteCategory` | Section title        |
   |-----------------|----------------------|
   | TECHNOLOGY      | Technical Index      |
   | RADAR           | AI Radar             |
   | LEADERSHIP      | Leadership Signals   |
   | COURSES         | Courses              |

   **Slice pipeline (`email_section_id` set):** **`RouterAgent`** returns **exactly one `RouteCategory` per persisted section**. Mixed-topic newsletters use **multiple DOM sections** (after **`normalize_sections_for_routing`**), routed independently with **`TechnologySectionOutput`**, **`RadarOutput`**, **`LeadershipSectionOutput`**, **`CoursesOutput`/noise** per slice; **`DigestComposer`** maps rows into digest columns (**not** legacy whole-email **`TechnologyOutput`** bundle fan-out).

   **Legacy rows:** **`email_section_id` NULL** history may retain **`TechnologyOutput`**, **`LeadershipOutput`**, or nested payloads (`leadership_excerpt`, `roundup_radar`, `session_promos`, …); **`DigestComposer`** may still flatten those envelopes when reloading old JSON. Persisted routers that emitted legacy **`MULTI_BUNDLE`** / **`EVERY_BUNDLE`** normalize to **`TECHNOLOGY`** while preserving stored payloads verbatim.

6. **Quality gate:** **`DigestQualityGateAgent`** inspects HTML (garbled output, suspicious unescaped markup, broken structure, etc.). **Retry semantics:** **first draft + up to 2 rewrites driven by `problems` = at most 3 generations**; if the third still fails, raise **`QualityGateFailedException`** (or the project’s chosen exception).
7. **Send:** after the gate passes, **`GmailSender.send_html`**.
8. **Only after send succeeds** (for messages **included in this digest**):
   - **`GmailLabeler.add_labels(message_id, [AI_DIGEST_PROCESSED], remove=[INBOX])`** — single user-visible label **`AI_DIGEST_PROCESSED`** and archive out of inbox;
   - DB: set **`emails.status`** to **`'archived'`** (§I.1).
9. **`finally`:** call **`release()`** only if this run **successfully `acquire()`’d**.

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

- Contract details (section vs legacy payloads, **`email_section_id`**, category → template headings): **§II.1 step 5** above.
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
7. **Section pipeline / Step 5 style tests:** multi-section mixed routing (four headings → four categories), deterministic **`RouterAgent`** fakes keyed by **`section_heading` / `section_key`** (see **`docs/section-extraction.md`** § *Testing section routing across retries* — **avoid** list **`side_effect` queues** across failure/retry), processor failure ⇒ **omit entire email from digest**, **`get_latest_outputs_by_email_ids`** ⇒ latest per **`(email_id, email_section_id, kind)`**, slice cache/`replace_email_sections` stability exercised in **`tests/test_step5_section_digest_integration.py`** + **`tests/test_repository_sections.py`**.

---

## IV. Reference files (implementation checklist)

- **`app/gmail/labeler.py`:** **`PROCESSED_LABEL`**, **`category_label_name`**, **`archive`** semantics.
- **`app/gmail/sender.py`:** what counts as send success.
- **`app/models/outputs.py`:** **`RouteCategory`**, **`RouterDecision`**, section-native payloads (**`TechnologySectionOutput`**, etc.).
- **`app/digest/composer.py`** / **`app/digest/templates/daily_digest.html.j2`**.
- **`app/storage/repository.py`:** **`fetch_unprocessed_emails`** / **`fetch_retryable_errors`** / **`attach_email_to_digest`** / **`update_email_status`** / **`replace_email_sections`** / **`section_pipeline_outputs_cached`**.
- **`docs/section-extraction.md`:** section invariants + **retry-test guidance** for router mocks.

---

**This document is the single source of requirements for Milestone 5.** If local code disagrees, align implementation and tests with this spec and existing DB/query conventions.
