# Milestone 3: Newsletter HTML parsing

**Scope:** Turn raw Gmail HTML into structured fields suitable for routing and processor agents: cleaned plaintext, ordered link lists, ranked image URLs, and a best-effort **`original_url`** (canonical / view-in-browser / first substantive anchor).

**Prerequisite:** Milestone 2 (**`fetch_message_html`** produces HTML).

**Current repo pointers:** `app/parsing/parser.py`, `app/parsing/link_extractor.py`, `app/parsing/html_cleaner.py`, `app/parsing/image_extractor.py`, `app/parsing/chunking.py`, `app/parsing/rules.py`, `tests/test_parsing_newsletter_html.py`.

---

## Deliverables

### 1. `ParsedHtmlResult` (`app/parsing/parser.py`)

| Field | Meaning |
|-------|---------|
| **`plain_text`** | Paragraph-oriented text after HTML cleaning (chrome/noise reduced). |
| **`plain_text_chars`** | Length for downstream chunking / window budgeting. |
| **`links`** | Ordered HTTP(S) URLs from **`collect_article_links_ordered`** (navigation noise stripped). |
| **`image_urls`** | Ranked illustration candidates from **`collect_ranked_images`**. |
| **`original_url`** | Single “read online” hint from **`resolve_original_url`** (canonical link, view-in-browser, or first non-noise anchor). |

**`parse_newsletter_html(html, base_hint=None)`** builds a dedicated BeautifulSoup tree for structure extraction and a separate pass for plaintext where required so image scraping order stays valid.

### 2. Link extraction (`app/parsing/link_extractor.py`)

- **`absolutize_html_url`**, **`collect_article_links_ordered`**, **`article_link_candidates`** (drops obvious image asset URLs from article lists).
- **`resolve_original_url`** — prefers **`<link rel="canonical">`**, then “view in browser” anchor phrases (from **`rules`**), then first anchor passing **`excludes_original_url_candidate`**.
- Filters for unsubscribe/footer URLs, tracking hosts, social chrome, and noisy query params (**`rules`** + **`url_has_tracking_query`** helpers).

### 3. HTML cleaning (`app/parsing/html_cleaner.py`)

- Strips boilerplate and converts markup to readable plaintext input for the **router** (subject + plain body).

### 4. Images (`app/parsing/image_extractor.py`)

- Collects candidate **`src`** URLs suitable as **`selected_image_urls`** allowlists for technology extraction.

### 5. Chunking (`app/parsing/chunking.py`)

- **`chunk_text`** (and related) for oversized newsletters before LLM calls — keeps ingestion within model limits without losing Milestone 4 contract fields.

### 6. Tests

- Fixture HTML asserts **`original_url`**, link ordering, canonical vs body links, “only chrome links” → **`None`**, multi-newsletter patterns where applicable.

---

## Relationship to later milestones

- **Milestone 4** agents consume **`ParsedHtmlResult`** (technology) or plaintext (router/radar/leadership/noise).
- **Technology** pipeline uses **`article_link_candidates`**, **`original_url`**, and image lists with Pydantic **`validation_context`** for allowlisted URLs.
- **Digest composer** (Milestone 5+) does not re-parse HTML; optional enriched fields (e.g. **`digest_source_url`** on technology output) originate from this parsing stage.

---

## Explicitly out of scope for M3

- Structured JSON outputs and prompts (**Milestone 4**).
- Persisted digest HTML and **`DailyDigestAgent`** (**Milestone 5**).

---

## Acceptance criteria (retroactive)

1. **`parse_newsletter_html`** is deterministic for fixed HTML inputs (tests locked).
2. **`links`** and **`original_url`** suppress obvious footer/tracking/social noise per **`rules`**.
3. Parser modules remain **importable and testable** without Gmail or OpenAI credentials.
