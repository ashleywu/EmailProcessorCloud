# Section extraction invariants

The parser produces a **global** `plain_text` / `links` / `image_urls` and a **scoped** list of **`EmailSection`** rows.

**Consumption rule (Step 1 hardening):** section-level routing and processors should ingest **`ParsedHtmlResult.sections`** directly. **Do not unify** merge global `plain_text` with per-section `text` in this step—they are built on different pipelines; keep them separate until a later refactor explicitly defines a combined view.

Agents that classify or extract **per slice** must treat **`section.links`** and **`section.image_urls`** as the **canonical URL sources** for that slice, not global lists and not inferred from **`section.text`**.

## Invariants

1. **`section.links`** — Authoritative ordered list of **section-scoped** `https:` URLs harvested from **`a[href]`** nodes that still exist inside the slice’s DOM range.

   **Sectionizer preserves anchors:** `_prepare_soup_for_sectioning` intentionally **does not** run **`_unwrap_navigation_links_into_text`**, so `<a>` elements remain parseable while walking each section’s node range.

   Dedup preserves first-seen order. Downstream allowlists should use **`section.links`**, not `ParsedHtmlResult.links` alone.

2. **`section.image_urls`** — Authoritative ordered list of **section-scoped** image URLs from **`img`** nodes in that range (absolutized, with the same pixel/logo/chrome filters as whole-document scraping).

   **Sectionizer preserves `<img>` tags:** preprocessing does **not** run **`_replace_media_with_readable_spans`** (which would strip `<img>` for global plaintext parity). Sections still carry images so **`section.image_urls`** stays meaningful.

3. **`section.text`** — **LLM-readable** plaintext (noise scrubbing similar in spirit to global plaintext, but sliced by DOM boundaries). Use it **for prose only**. **`href`** and image URLs generally **must not be inferred** solely from **`section.text`**; use **`section.links`** / **`section.image_urls`** for anything URL-shaped.

4. **Global `plain_text` vs `section.text`** — `plain_text` comes from **`html_to_plaintext_soup`** on a **fresh** parse and may unwrap anchors. **`section.links` still retains `href`** for that slice regardless. Consumers must not treat “URLs missing from `plain_text`” as “no links.”

5. **`section_count` and cardinality** — `ParsedHtmlResult.section_count` equals `len(sections)`. `parse_newsletter_html` requires **≥ 1** section; when headings cannot be inferred, the sectionizer returns **exactly one** fallback section covering the (pruned) document.

## `EmailSection` fields (every row)

Stable identity and payload for metrics + downstream joins:

| Field | Notes |
|--------|--------|
| **`section_id`** | Stable handle within one email (`"s0"`, `"s1"`, …). |
| **`order_index`** | Matches reading order (`0 … n-1`). |
| **`heading`** | Populated when the slice starts from a detected heading; otherwise `None` (e.g. preamble or fallback). |
| **`text`** | Section prose for LLMs; not a MIME-complete representation. |
| **`links`** | Section-scoped `https`, authoritative. |
| **`image_urls`** | Section-scoped images, authoritative. |
| **`email_id`** | Optional until persisted alongside DB email rows. |

Correlation with routing logs: pair **`section_id`** / **`order_index`** with **`message_id`** / DB **`email_id`** when persisting outputs.

## Persistence (`email_sections` + `agent_outputs`)

After extraction, **`StateRepository.replace_email_sections`** stores one row per section: parser **`EmailSection.section_id`** maps to DB **`section_key`** (unique per **`email_id`**), alongside **`heading`**, **`text`**, **`links_json`**, **`image_urls_json`**, and **`order_index`**. Replacing sections runs in a transaction and **drops old section rows** (`DELETE` scoped to that email); **`agent_outputs`** rows tied via **`email_section_id`** cascade away with the section FK.

Latest outputs for compose are keyed by **`(email_id, email_section_id, kind)`** — two sections may each have a **`technology`** row without collapsing. **`email_section_id`** may be **`NULL`** for legacy “whole email” pipeline rows; **`try_reuse_complete_outputs`** intentionally only considers that legacy shape.

Router rows may set **`category`** (canonical uppercase **`RouteCategory`**) for query convenience; it must agree with **`RouterDecision.category`** in the JSON payload when both are supplied.

## Testing section routing across retries

When mocking **`RouterAgent.run`** for tests that simulate **failure + retry**:

- Prefer a **deterministic** implementation keyed by **`section_heading`**, parser **`section_id`** / DB **`section_key`**, **`EmailSection.text`** fingerprints, **`content_hash`**, etc.—anything stable per logical slice across runs.
- **Avoid list-based `side_effect` queues**: a failing run stops at the **first** exception and may invoke `_router.run` fewer times than sections in the mailing. Items left in the queue are still consumed on the next attempt, so the retry can be routed to the **wrong** category despite correct cache/`email_sections.id` semantics.

Example:

```python
router.run.side_effect = lambda **kw: route_from_heading(section_heading=kw.get("section_heading"))
```
