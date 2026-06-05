# Prompt files (`app/prompts/`)

## Section-scoped digest pipeline (production today)

Loaded by section agents via ``load_prompt("{stem}")``:

| Stem | Loaded by |
|------|-----------|
| `router` | `RouterAgent` — **fallback path**; after Phase 6, not primary for trusted/mixed senders |
| `technology_section` | `TechnologyProcessorAgent` |
| `leadership_section` | `LeadershipProcessorAgent` |
| `radar` | `RadarProcessorAgent` |
| `courses` | `CoursesProcessorAgent` |

## AINews / map-reduce Radar (configured senders)

See [`docs/map-reduce-radar-design.md`](../docs/map-reduce-radar-design.md). **No** `RouterAgent` or content-unit classifier.

| Stem | When |
|------|------|
| `ainews_radar_hero` | Hero → Top Story card |
| `ainews_radar_map` | Map phase |
| `ainews_radar_reduce_recap` | Recap sections |
| `ainews_radar_reduce` | Full issue without recap boundary |

## Content-unit pipeline (Phase 6 — design)

Two-step flow per grouped **content unit**:

1. **Classify** — `content_unit_classifier` → `ContentUnitClassificationResult`  
2. **Extract** — exactly one of `content_unit_*` processors after `ProcessorDispatcher`

Policies: [`docs/content-unit-classifiers.md`](../docs/content-unit-classifiers.md). Architecture: [`docs/content-unit-routing-design.md`](../docs/content-unit-routing-design.md).

| Step | Stem | Output model |
|------|------|--------------|
| Classify | `content_unit_classifier` | `ContentUnitClassificationResult` |
| Extract | `content_unit_radar` | `RadarOutput` |
| Extract | `content_unit_technology` | `TechnologySectionOutput` (`original_url` may be null) |
| Extract | `content_unit_leadership` | `LeadershipSectionOutput` |
| Extract | `content_unit_courses` | `CoursesOutput` |

Extract prompts assume classification is already done — **no** `matches` / reject fields.

Interview long-form (Latent Space / ByteByteGo prior): continue using `technology_section_interview.md` when `processor_hint=technical_interview_transcript`.

## Legacy (whole-email processors)

| Stem | Notes |
|------|-------|
| `technology.md` | Deprecated monolithic `TechnologyOutput` |
| `leadership.md` | Deprecated `LeadershipOutput` |

No agent imports these after the section-level refactor.
