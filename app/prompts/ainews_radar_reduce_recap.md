# AINews recap phase — 0–2 Radar Recap cards

You receive facts extracted from **recap sections** only (from the first recap boundary onward: AI Twitter Recap, AI Reddit Recap, community roundups, etc.).

**RADAR only.** These are **Recap** cards under AI Radar — not Technical Index or Leadership.

Reply with **only** a JSON object. No markdown fences, no extra text.

## Output JSON schema

| Field | Type | Rules |
|--------|------|--------|
| `cards` | array | **0 to 2** items. Each must have `role` = `"recap"`. |

Each card:

| Field | Type | Rules |
|--------|------|--------|
| `role` | string | Must be `"recap"`. |
| `title` | string | Thematic recap label (e.g. "AI Twitter recap: agents and harnesses") |
| `tldr` | string | One or two sentences for **this recap thread** |
| `key_points` | array | **At most 7** bullets |
| `why_it_matters` | array | **At most 3** |
| `watchouts` | array | **At most 3** |

## Grouping rules

- **0 cards** if recap facts are too thin or redundant after filtering.
- **1 card** when Twitter/Reddit/community content merges into one community recap theme.
- **2 cards** when distinct substantial threads exist (e.g. separate **AI Twitter Recap** vs **AI Reddit Recap** themes).
- **Never** one card per original section or per `source_heading`.
- Prefer `importance_score` ≥ 4; drop score 1–2 and sponsor noise.

## Input

Optional **subject** and **facts JSON** from recap sections only.
