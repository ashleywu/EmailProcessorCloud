# Technology section processor — exactly one TECH slice per section

Reply with **only** JSON representing **one** `TechnologySectionOutput` object for **this routed section**:

| Field | Type | Rules |
|--------|------|--------|
| `title` | string | Concise headline for the technical read (≤500 chars). |
| `core_pain_point` | string | Sharp problem framing (≤240 chars). Not a paragraph summary — one tight insight. |
| `original_url` | string | **HTTPS** Article / primary canonical URL copied **verbatim** from the numbered candidate article list supplied in the user message — must match **exactly** one entry. Never invent URLs. |
| `diagrams` | array | `Diagram` (`title`, `diagram_type`, `content`) preserving substantive ascii/mermaid snippets from the excerpt; omit or use `[]`. |

Constraints:

- Ignore incidental radar chatter, stray leadership tones, or promo lines **inside this slice** when they do not describe the technical read; prioritize the substantive **technical article / explainer** in **this routed section**.
- `original_url` must be HTTPS and **must equal** one of the candidate URLs in the numbered list labeled for article/original URLs.
- Respond with plain JSON — no fences, extra keys, or commentary.
