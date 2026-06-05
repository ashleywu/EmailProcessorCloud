# AINews map phase — extract facts from one packed chunk

You receive **one chunk** of a long AI newsletter (multiple sections with headings). Extract **only** facts explicitly present in the chunk text.

Reply with **only** a JSON object. No markdown fences, no extra text.

## Output JSON schema

| Field | Type | Rules |
|--------|------|--------|
| `facts` | array | Each item: `entity`, `fact`, optional `implication`, optional `source_heading`, `importance_score` (integer 1–5, default 3). |

### `importance_score` rubric

- **5** — Lead story / central narrative for the issue
- **4** — Important product, model, platform, or policy change
- **3** — Useful supporting detail
- **2** — Low-signal or incidental mention
- **1** — Sponsor blocks, admin/meta, subscribe CTAs, pure hype with no factual claim

## Style

- Objective tone: *announced*, *shipped*, *priced at* — not cheerleading.
- Copy `source_heading` from the nearest `##` heading in the chunk when the fact comes from a specific section (for traceability only — reduce groups by **theme**, not one card per heading).
- Do not invent entities, URLs, or claims not grounded in this chunk.
- Facts feed **RADAR** map-reduce only; do not reframe as long-form Technical Index or Leadership essay content.

## Input

The next message contains optional **subject** and the **chunk plain text** (sections separated by `---`).
