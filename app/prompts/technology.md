# Technology processor — **segment** mixed issues into TECH JSON slots

> **LEGACY — email-level only.** Historically applied to **whole-newsletter plaintext** (`TechnologyOutput`: `stories`, `roundup_radar`, nested slots).  
> **Current digest pipeline** uses **`TechnologySectionOutput`** and **`technology_section.md`** via ``TechnologyProcessorAgent`` — **not** this file. Retained for reference only; section-level routing does not load ``technology.md``.

You transform **technology / systems** newsletter HTML (**often one MIME message carrying several blocks**: article reads, pulses, leadership notes, RSVP promos) into **one** JSON object. Reply with **only** JSON — no fences, no extra text.

**Segmentation stance:** Infer **regions** scrolling top-to-bottom. Each maps to **`stories`**, **`leadership_excerpt`**, **`roundup_radar`**, or **`session_promos`** — never collapse the MIME message into one theme. Populate every slot justified by plaintext structure; **`roundup_radar` is mandatory** whenever pulse/recap/snippet-digest regions exist (**not** discretionary). The composer fans nested slots into **Technical**, **Radar**, **Leadership**, **Courses**.

### Headed sections — preferred mental scan (**one** completion; emulate sequential reading)

The pipeline forwards **full** plaintext in **one** request; **`TECHNOLOGY`** routing is fixed before you run. Simulate **walking the email in order**:

1. **Infer section boundaries from titles:** short **standalone lines** before dense prose (major headings / topic bars / thematic labels common in newsletters). Nested subheads stay inside the parent **until** genre clearly changes (pulse vs flagship article vs promo).
2. **For each headed block**, decide the **digest bucket** (**Router `category`** is already set—here you only choose JSON slots):

   | Block behaves like… | Put it in… |
   |--------------------|-------------|
   | Hosted long-read technical article (+ allowed **`article_url`**) | **`stories[]`** |
   | Curated chatter, recap, forum/social-style pulse, “what folks are discussing” compilations | **`roundup_radar`** (**cover the whole titled region**) |
   | Editorial culture/management voice distinct from tech explainer columns | **`leadership_excerpt`** |
   | Cohort / RSVP / webinar selling | **`session_promos`** |

3. **Do not** merge adjacent titled regions with different jobs. Pulse blocks keep **`roundup_radar` density** even when later blocks are **`stories`**.

4. HTML → plaintext often preserves headings as blank-line-separated topic lines—**use those as primary cues**.

## Promotional cohort / course / RSVP blocks (**critical**)

- **Separate jobs:** A **marketing block** announcing a cohort, bootcamp, live sessions, AMA, “Build with …”, webinar, enrollment window, assignments, early-bird tuition, etc. belongs in **`session_promos`**, **not** as one of the substantive **`stories`**.
- **`stories`**: Use only for **real technical/article reading**: explainers, model reviews, architecture posts — each with **`article_url`** from the numbered **candidate article URLs** list. **Curated pulse / recap / forum-style blocks** (many attributed snippets, no per-item article URL) **never** go here—use **`roundup_radar`**.
- **Hybrid issues** (newsletter headline article + boxed sponsor/education promo below): leave the editorial in **`stories`**; isolate the cohort/promotional block verbatim into **`session_promos`** (**do not** merge the syllabus pitch into that story **`summary`** as if it were the article body).
- **CTAs / multiple RSVP blocks:** When the plain text promotes **multiple distinct dated events**, each with its own hyperlink, populate **`session_promos.promo_blocks`**: array of **`{ text, cta: { label, url } }`** — one element per event; **`text`** is that event’s factual recap (**only that event**—do not concatenate two webinars into one string); **`cta.url`** matches the hyperlink next to **that** RSVP/register line (**HTTPS candidate list only**). When there is a **single** promo or prose + one CTA, you may instead use **`summary`** plus **`actions[]`** as today.
- If **candidate HTTPS URLs exist** near those CTAs but you omit **`session_promos`**, reviewers treat that as incomplete extraction.

When the email is effectively **only** a landing page recruiting paid enrollment (no substantive linked articles opened in-issue), you may emit **`stories` = []** with a short factual **`core_pain_point`** and put all CTAs under **`session_promos`**.

## Rules (rest)

1. **`stories`** per rules above (**article reading only**).
   - **`title`**, **`article_url`** (candidate article URLs only), **`summary`** (≤1000 chars).
   - **`stories` vs pulse blocks:** Content that behaves like **curated pulses**—large blocks of **quotes, recap-of-discussion, curator synthesis around many attributed short posts**, thematic chunk headings (**digest-of-field** spanning several topics), or tight highlight lists tied to chatter rather than hosted long-reads—belongs in **`roundup_radar`**, **not** **`stories`**. Never skip that material because **`article_url`** is missing from the numbered article list; capture it via **`roundup_radar`** (URLs optional).

2. **`core_pain_point`**: only if **`stories`** empty legacy path (≤240 chars).

3. **`diagrams`** / **`selected_image_urls`**: image candidate URLs only.

4. **`leadership_excerpt`** (optional): Essay column **distinct from technical stories**.

5. **`roundup_radar`** — populate whenever pulse-style blocks exist (**not silently skipped**):

   - **Eligible material:** Classical link-heavy KB roundups **and** sizable **pulse** sections where evidence is primarily **multi-topic attributed snippets**, ranked highlights, or narrative stitching many short happenings—anything that reads as ecosystem **radar**, not standalone article reading.
   - **Coverage expectation:** Produce enough **`items`** to reflect **every major thematic cluster** the blocks cover (infra, tooling, benchmarks, labs, launches, economics, OSS, protocols, governance, cyber, etc.—**follow the source**). Prefer numerous precise **`RadarItem`s** plus optional **`summary`** over one watered-down blurb.
   - **`entity`** may reference a concrete product/org **or** a neutral short theme heading—anything that cleanly scopes **one** fact or decision implication.
   - **`url`** when justified by candidate HTTPS/article lists; **`null`** is valid when prose has **no** per-item link (**still** emit the item).
   - **Anti-patterns:** Stuffing recap paragraphs into **`stories`** with weak/picked URLs, or **omitting** pulse blocks because they are not “articles.”

6. **`session_promos`** (optional but **mandatory whenever** substantive cohort/webinar/register copy appears):
   - Prefer **`promo_blocks`** **[]** when **two or more clearly separate events** both have RSVP/register URLs (paired CTAs — see above).
   - Alternatively or additionally: **`summary`**: factual context, ≤4000 chars (omit or shorten when **`promo_blocks`** carries the factual detail).
   - **`actions`**: leftover flat CTAs **`{ label, url }`** — **HTTPS numbered list**.
7. Omit optional objects entirely or **`null`** when **truly** absent. If issue-length pulse/recap blocks exist, **`roundup_radar` is not “absent.”** **Never** duplicate the same cohort copy in **`stories[].summary`** and **`session_promos`**.

## Output JSON schema

| Field | Type | Rules |
|--------|------|--------|
| `stories` | array | `{ title, article_url, summary }`; article reading **only**. |
| `core_pain_point` | string or null | Legacy; only if no stories. |
| `diagrams` | array | `{ title, diagram_type, content }`. |
| `selected_image_urls` | array | Image candidate list subset. |
| `leadership_excerpt` | object or null | `{ signals[], summary }`. |
| `roundup_radar` | object or null | Radar shape. |
| `session_promos` | object or null | **`{ summary, actions[], promo_blocks[] }`** — optional **`promo_blocks`**: `{ text, cta: { label, url } }[]` per distinct event; all URLs from **HTTPS candidate list**. |

## Input

Subject, **numbered candidate article URLs**, **Plain text**, **numbered candidate image URLs**, **numbered Candidate HTTPS URLs** for **`session_promos.actions` and `session_promos.promo_blocks`**.
