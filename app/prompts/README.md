# Prompt files (`app/prompts/`)

## Section-scoped digest pipeline (current)

Production agents resolve these stems via ``load_prompt("{stem}")``:

| Stem | Loaded by |
|------|-----------|
| `router` | `RouterAgent` |
| `technology_section` | `TechnologyProcessorAgent` |
| `leadership_section` | `LeadershipProcessorAgent` |
| `radar` | `RadarProcessorAgent` |
| `courses` | `CoursesProcessorAgent` |

Canonical tuple: ``SECTION_PIPELINE_PROMPT_STEMS`` in ``app/agents/_prompts.py``.

## Legacy (whole-email processors)

These markdown files remain in the repo for historical reference **only**:

- ``technology.md`` — old monolithic ``TechnologyOutput`` instructions.
- ``leadership.md`` — old ``LeadershipOutput`` with nested radar/session slots.

Canonical tuple: ``LEGACY_EMAIL_LEVEL_PROMPT_STEMS`` in ``app/agents/_prompts.py``. **No agent** imports them after the section-level refactor.
