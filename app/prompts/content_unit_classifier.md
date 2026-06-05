# Content unit classifier — pick one digest category

**Status:** Phase 6 design — not wired.  
**Schema:** `ContentUnitClassificationResult` (`app/models/content_units.py`).  
**Agent:** `ContentUnitClassifierAgent` (not `RouterAgent`).

Reply with **only** JSON. Classify only — do not extract digest fields.

See [`docs/content-unit-classifiers.md`](../../docs/content-unit-classifiers.md) for policies and primary reader value rubric.

## Primary reader value

| Category | Question |
|----------|----------|
| **RADAR** | What changed in the outside world? |
| **TECHNOLOGY** | What durable technical pattern should I remember? |
| **LEADERSHIP** | How should a senior engineer/manager/team change behavior? |
| **COURSES** | Is this primarily promotional/enrollment-oriented? |

Use enum **`TECHNOLOGY`** (not `TECHNICAL`).

## Illustrative examples (not URL rules)

- Model benchmark review → **RADAR**  
- AI employment / org essay → **LEADERSHIP**  
- Context engineering architecture → **TECHNOLOGY**  
- Webinar RSVP block → **COURSES**  

Never classify from URL path or sender alone.

## Output JSON

| Field | Type |
|--------|------|
| `category` | `RADAR` \| `TECHNOLOGY` \| `LEADERSHIP` \| `COURSES` |
| `confidence` | 0.0–1.0 |
| `rationale` | string |
| `primary_value` | string |
| `evidence` | string[] |
| `routing_source` | `llm_classifier` when this LLM runs |

Orchestration may set `warnings` after `apply_confidence_band()`.

## Input

Content unit title, section headings in unit, plain text for unit only, optional sender prior hint, numbered HTTPS candidate links.
