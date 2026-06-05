# AINews reduce phase — full-issue thematic cards (no recap boundary)

Use this prompt only when the issue has **no** recap boundary (no "AI Twitter Recap" / "AI Reddit Recap" style split). When a boundary exists, hero and recap use separate prompts.

You receive a **merged list of facts** from map passes over the **entire** issue. Produce **1–3** thematic **RADAR** cards.

**RADAR only** — never Technical Index or Leadership. Group by **theme**, not by section headings.

Reply with **only** a JSON object. No markdown fences, no extra text.

## Card count (critical)

Output **1 to 3** cards. Choose the count from **how many substantive themes** exist — not from section count.

| Situation | Cards |
|-----------|-------|
| One dominant event or product launch drives the issue | **1** card |
| Clear main story **plus** separate substantial threads (e.g. Twitter recap, Reddit recap, secondary product wave) | **2–3** cards |
| Several unrelated major threads with enough facts each | **2–3** cards (cap at 3) |

**Do not:**

- Collapse the **entire issue** into a single card when **2+ distinct themes** each have multiple score-4/5 facts.
- Emit **one card per original section** or per `source_heading` (never 10+ cards; schema allows max 3).
- Use section titles as card titles — write **short thematic labels** instead.

**Do:**

- Cluster mapped facts by theme (product launches, community recaps, infra/agents, policy, etc.).
- Put Twitter/Reddit/community roundup facts into **their own card** when they form a coherent second or third theme.
- Keep each card skimmable: one theme, one `tldr`, focused `key_points`.

## Examples (illustrative patterns)

**1. Microsoft Build / MAI issue** — likely **1** card (optional **2** if other updates are substantial):

- "Microsoft Build: MAI-Thinking-1 and MAI family models"

**2. Reve 2 + Ideogram 4 + social recaps** — likely **2–3** cards:

- "Generative media models: Reve 2 and Ideogram 4 Layouts"
- "AI Twitter recap: agents, coding workflows, and infra"
- "AI Reddit recap: local and open-model community signals"

**3. Founders + forward-deployed engineers** — likely **1–2** cards:

- "Founders and forward deployed engineers"
- "Agent harnesses and multi-turn RL infrastructure" (second card only if substantial)

## Fact selection

- Prefer `importance_score` **≥ 4** for titles and key points.
- Use score **3** only for context within a theme.
- **Drop** score **1–2** and sponsor/admin/noise facts.

## Output JSON schema

| Field | Type | Rules |
|--------|------|--------|
| `cards` | array | **1 to 3** thematic recap cards |

Each card:

| Field | Type | Rules |
|--------|------|--------|
| `title` | string | Thematic label (not a pasted newsletter heading) |
| `tldr` | string | One or two neutral sentences for **this theme only** |
| `key_points` | array of strings | **At most 7** bullets; concrete facts for this theme |
| `why_it_matters` | array of strings | **At most 3** bullets; implications |
| `watchouts` | array of strings | **At most 3** bullets; risks or caveats (omit if none) |

## Style

- Objective radar tone: *announced*, *shipped*, *priced at* — no hype.
- Bullets stand alone without the source email.

## Input

The next message contains optional **subject** and **facts JSON** (`entity`, `fact`, `implication`, `source_heading`, `importance_score`).
