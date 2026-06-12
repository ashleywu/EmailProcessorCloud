# Phase 7.1 backlog — trigger tuning & polish

**Status:** Not started. **Prerequisite:** Phase 7 minimal safety path merged (P0 hard-boundary fix + boundary orchestration live).

**Related (planned):** [`sender-profiles.md`](sender-profiles.md) (profile fast path; BC/classifier skipped on happy path), [`interrupt-grouping.md`](interrupt-grouping.md) (shared interrupt roles + generic fallback grouping).

**Purpose:** Close the gap between §4 target policy and shipped `_is_ambiguous()` behavior, align docs/tests, then **freeze Phase 7**.

**Not in scope:** Phase 8 (LINK_AGGREGATOR map-reduce), `dropped_sections`, RouterAgent rename.

---

## Why this is a separate PR

Phase 7 shipped the **safety path**: per-run boundary LLM, raw-order validation, cross-promo merge rejection, shared fallback builder, audit persistence.

The **`ambiguous` trigger is intentionally not final** in that merge. A broader gray-zone heuristic is acceptable temporarily because:

- False merge across promo is blocked regardless of trigger breadth.
- Conservative fallback remains available on validation/budget/LLM failure.
- Tightening the trigger changes which emails call the boundary LLM and **breaks many integration fixtures** — that migration belongs in one focused PR, not mixed with the safety fix.

Reviewers: items in this backlog are **deferred by design**, not bugs missed in Phase 7.

---

## Exit criterion

When every checkbox below is done:

1. Run full `tests/` (including updated Phase 7 fixtures).
2. Update `phase7-boundary-classifier.md` §4 to “shipped” wording (remove interim trigger callout).
3. Mark this file **Status: Complete** and stop Phase 7 feature work.

---

## 1. Tighten `_is_ambiguous()` (structure-local only)

**File:** `app/parsing/content_unit_grouping.py`

- [ ] Add `_is_promo_dominated(promo_flags)` in `group_content_units()` → `ambiguous=False` when `promo_count / total > 0.5`
- [ ] Gray zone `3 <= non_promo_count <= 8` remains a **gate**, not a sufficient trigger
- [ ] `url_count=0` alone → `ambiguous=False`
- [ ] `url_count >= 3` → `ambiguous=False` (clear aggregator; already implemented)
- [ ] Clear numbered chapter sequence (≥2 chapter headings) → `ambiguous=False` (already implemented)
- [ ] High-confidence long-form → `ambiguous=False` (already implemented)
- [ ] Require **≥1 explicit local signal** for `ambiguous=True`:
  - [ ] `MIXED_HEADING_PATTERN` (`_has_mixed_heading_pattern`)
  - [ ] `AMBIGUOUS_URL_COUNT` (`1 <= url_count <= 2`; decide whether standalone headings are required)
  - [ ] `MIXED_CHAR_DISTRIBUTION` (optional third signal — confirm in PR)
- [ ] `SECTION_COUNT_GRAY_ZONE` in `ambiguity_reasons` is context only when `ambiguous=True`; must not alone trigger boundary

**Explicitly defer (do not add to `_is_ambiguous()` in 7.1 unless data already available):**

- [ ] `sender_prior_mismatch` — orchestrator-level: `grouping.ambiguous OR sender_prior_mismatch(...)`
- [ ] `transcript/interview` heading or Q&A density heuristic

---

## 2. Tests

**File:** `tests/test_phase7_boundary_classifier.py` (+ shared helpers)

### New unit tests

- [ ] Plain 3 non-promo sections, no ambiguity signal → `ambiguous=False`
- [ ] `url_count=0` alone (4 standalone sections) → `ambiguous=False`
- [ ] Mixed heading and/or weak URL evidence → `ambiguous=True`
- [ ] Promo-dominated (>50% promo sections) → `ambiguous=False`
- [ ] Numbered chapters → `ambiguous=False`
- [ ] Clear multi-url aggregator (≥3 primary URLs) → `ambiguous=False`

### Integration fixture migration

Update fixtures that assume **“N sections in gray zone ⇒ boundary runs”** without explicit signals:

- [ ] Replace `_ambiguous_html()` (Topic A–D, no URLs) with mixed-heading or weak-URL variant
- [ ] `test_ambiguous_every_like_email_sets_ambiguous_true` — fixture must include explicit signal
- [ ] `test_boundary_classifier_triggered_for_ambiguous_email`
- [ ] Fallback / validation / budget / low-confidence tests using `_ambiguous_html()`
- [ ] P0 per-run promo tests if they rely on loose ambiguous trigger

### outline_hash persistence

- [ ] Integration test: `monkeypatch` `_BOUNDARY_MAX_PROMPT_CHARS` to force `SNIPPET_TRUNCATED`
- [ ] Assert persisted `agent_outputs.kind=boundary_classifier` → `outline_hash == compute_outline_hash(sections sent to LLM)`
- [ ] Assert hash differs from pre-truncation (full snippet) outline

---

## 3. Documentation alignment

**Files:** `docs/phase7-boundary-classifier.md`, `docs/content-unit-classifiers.md` (§6 footnote if needed)

- [ ] §3: “must be refactored” → shipped `GroupingResult` wording
- [ ] §4: remove interim “shipped vs target” callout; document final trigger rules
- [ ] §7.1: `classify_boundaries(...) -> BoundaryLLMOutput`; remove stale `budget` / `BoundaryClassificationResult` on agent
- [ ] §14: note orchestrator wraps agent output into `BoundaryClassificationResult` for persistence
- [ ] Known gaps section in `phase7-boundary-classifier.md` → point here until complete, then shorten to “Phase 7 frozen”

---

## 4. Suggested PR title (when ready)

```
chore(phase7.1): tighten ambiguous trigger, fixtures, outline_hash test, docs
```

**Single PR.** Do not split into ambiguous-tighten PR + docs PR + test PR (fixture churn conflicts).

---

*Created: 2026-06-05 — companion to [`phase7-boundary-classifier.md`](phase7-boundary-classifier.md)*
