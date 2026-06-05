# AINews hero phase — one Radar Top Story card

You receive **hero sections** from an AINews issue: everything **before** the first recap boundary (e.g. before "AI Twitter Recap"). This is the **lead story** of the issue — product launches, main narrative, keynote news.

**RADAR only.** Do not write Technical Index article blurbs or Leadership essays. One **Top Story** card for AI Radar.

Reply with **only** a JSON object. No markdown fences, no extra text.

## Output JSON schema

| Field | Type | Rules |
|--------|------|--------|
| `card` | object | Exactly **one** Top Story card with `role` = `"top_story"`. |

The `card` object:

| Field | Type | Rules |
|--------|------|--------|
| `role` | string | Must be `"top_story"`. |
| `title` | string | Thematic label for the hero story (e.g. "Reve 2 and Ideogram 4: layout-native imagegen") — not a pasted section heading |
| `tldr` | string | One or two neutral sentences |
| `key_points` | array | **At most 7** concrete bullets from hero sections only |
| `why_it_matters` | array | **At most 3** implications |
| `watchouts` | array | **At most 3** caveats (omit if none) |

## Rules

- Synthesize **one** card from all hero text — do not split into multiple cards.
- Prefer the dominant product/event thread; drop sponsor/admin noise.
- Objective tone; facts grounded in the hero plain text only.

## Input

Optional **subject** plus **hero plain text** (sections separated by `---`).
