# Milestone 8: Content-unit routing (Phase 6 live switch)

**Prerequisite:** Milestones 1–7 complete; section pipeline (`RouterAgent` + `run_section`) and AINews map-reduce stable.

**Goal:** Route trusted priors and mixed publications through **group → classify → extract**; keep **`RouterAgent`** for fallback only.

**Design docs (normative):**

- [`docs/sender-profiles.md`](docs/sender-profiles.md) — profile fast path + generic fallback (planned)  
- [`docs/interrupt-grouping.md`](docs/interrupt-grouping.md) — shared interrupt detection + generic grouping (planned)  
- [`docs/map-reduce-radar-design.md`](docs/map-reduce-radar-design.md) — AINews path (unchanged)  

**Status:** Implemented for Phase 5–6; this remains the checklist for validation and future Phase 7/8 follow-up.

---

## I. Prerequisites (Phases 0–5)

Before flipping live routing:

| Phase | Requirement |
|-------|-------------|
| 0–4 | Models, outline, priors, sanity, decision logging (may be log-only until Phase 6) |
| 5 | `group_content_units(outline, prior, sanity_result) → list[ContentUnit]` with tests for trust / reject / HYBRID / promo units |

Grouping runs on **raw** section outline, not `normalize_sections_for_routing` output.

---

## II. New components (Phase 6)

### 1. Agents & helpers

| File | Responsibility |
|------|----------------|
| `app/agents/content_unit_classifier_agent.py` | LLM → `ContentUnitClassificationResult` |
| `app/agents/processor_dispatcher.py` | `RouteCategory` → processor + unit/section `run_*` |
| `app/processing/confidence_band.py` | `apply_confidence_band()` — policies §2, §7 |

**Option B (required):** new `ContentUnitClassifierAgent`; **do not** repurpose `RouterAgent`.

### 2. Orchestration (`DailyDigestAgent`)

New branch order:

1. Parse + structural outline  
2. Resolve sender prior + sanity → `selected_strategy`  
3. If AINews → existing map-reduce (unchanged)  
4. If content-unit strategy → group → per unit: classify → band → dispatch → processor  
5. If `generic_section_routing` → existing section loop with **added** `apply_confidence_band` on `RouterDecision`  
6. **All-or-nothing attach** (policy §8) before `attach_email_to_digest`  

### 3. Persistence

| `agent_outputs.kind` | When |
|----------------------|------|
| `classifier` | Content-unit path classification |
| `router` | Fallback section path (unchanged) |
| `technology` / `radar` / `leadership` / `courses` | Processor outputs |

Add **`content_unit_key`** to agent output rows (or agreed metadata) for multi-unit emails.

Populate `email_processing_decisions.outcome` with unit count, processor kinds, warnings.

### 4. Composer

- Join on `(email_id, content_unit_key)` for classifier + processor pairs (policy §10).  
- Fallback path: existing `(email_id, email_section_id)` join.  
- Skip incomplete pairs; emit warning if skipped rows exist on an attached email.  

### 5. Prompts

See [`app/prompts/README.md`](app/prompts/README.md):

- `content_unit_classifier` — classify only  
- `content_unit_{radar,technology,leadership,courses}` — extract only  

---

## III. Policies to implement (checklist)

Copy from [`content-unit-classifiers.md`](docs/content-unit-classifiers.md):

- [ ] §1 Processors never classify  
- [ ] §2–§7 Unified confidence bands on all sources  
- [ ] §8 All-or-nothing email attach  
- [ ] §9 Non-LLM confidence defaults (0.9 / 0.85 / 0.65)  
- [ ] §10 Composer pair join  
- [ ] Option B agent split (`ContentUnitClassifierAgent` + `RouterAgent` fallback + `ProcessorDispatcher`)  

Constants: `CLASSIFIER_CONFIDENCE_PROCESS=0.75`, `CLASSIFIER_CONFIDENCE_MIN=0.55`.

---

## IV. Required tests

1. **Prior trust** — ByteByteGo-like fixture → one unit → `sender_prior` → TECHNOLOGY processor, no LLM classifier call (mock).  
2. **Sanity reject** — falls back to `ContentUnitClassifierAgent` or heuristic.  
3. **Low confidence** — `< 0.55` → no processor, unit `classification_failed`, email not attached.  
4. **Mid confidence** — `0.65` weak heuristic → processor runs, `classification_low_confidence` in warnings.  
5. **Every multi-unit** — mock grouping → N classifier rows + N processor rows; no sender default category.  
6. **Any unit fail** — email `failed`, not in digest, not archived.  
7. **Fallback path** — sanity reject + unknown sender → `RouterAgent` still works; band applied to `RouterDecision`.  
8. **AINews** — still bypasses classifier and router.  
9. **Composer** — skips unit without processor pair; renders paired units only.  
10. **Decision replay** — `email_processing_decisions` + `kind=classifier` rows queryable by `email_id`.  

---

## V. Non-goals (Phase 6)

- LLM **boundary** classifier (Phase 7)  
- LINK_AGGREGATOR map-reduce reuse (Phase 8)  
- Renaming `RouterAgent` → `SectionClassifierAgent`  
- Partial digest attach (some units in, some out)  

---

## VI. Reference files

- `app/agents/daily_digest_agent.py` — orchestration  
- `app/agents/router_agent.py` — fallback only after Phase 6  
- `app/digest/composer.py` — unit pair join  
- `app/storage/repository.py` — agent output save/load  
- `config/sender_priors.json` — prior registry  

---

**This document is the implementation checklist for Phase 6 (Milestone 8).** Classification policy details live in `docs/content-unit-classifiers.md`.
