# Mixed Newsletter Shape Profile (V1)

**Status:** **Implemented**  
**Module:** `app/processing/newsletter_shape/`  
**Wired in:** `group_content_units()`, `DailyDigestAgent._process_content_unit_email()`  
**Related:** [`pipeline-flowchart.md`](pipeline-flowchart.md), [`sender-profiles.md`](sender-profiles.md) (sender **profile** fast path is separate)

Mixed newsletters (long-form essay + chrome sections + optional roundup blocks) share the same structural problem: the generic content-unit pipeline splits one story into many digest cards. This spec generalizes the former Every-only “digest shape” logic into a **profile registry**. **Every.to** and **Turing Post** are the first two instances.

---

## Goals (V1)

| Goal | Behavior |
|------|----------|
| Single long-form story | Merge eligible sections → **one** `ContentUnit` → one digest card |
| True multi-story (rare) | Split only with **strong evidence** (≥2 canonical story URLs, each block ≥400 chars) |
| Teaser / paywall only | **Skip** digest attach; label Gmail; `emails.status = skipped` |
| Default bias | When uncertain → **`single_article`** merge |

---

## Three digest shapes

| Shape | Meaning | Units | Digest attach |
|-------|---------|-------|---------------|
| `single_article` | One story | 1 merged unit | Yes |
| `multi_story` | Multiple distinct stories (strong evidence) | 1 unit per canonical URL | Yes |
| `teaser_paywall` | No substantive body (<400 article chars after filters) | 0 | **No** |

Classifier: `classify_newsletter_shape()` in `shape_classifier.py`.

---

## Profile registry (V1)

Lookup: `lookup_newsletter_shape_profile(sender, original_url)` in `registry.py`.

| `profile_id` | Senders | Primary URL whitelist | Notes |
|--------------|---------|----------------------|-------|
| `every_to` | `hello@every.to`, `every@every.to`, `@every.to` | `every.to/{pub}/{slug}` or `/p/{slug}` | Unwrap `icu.every.to/CL0/…` tracking |
| `turing_post` | `turingpost@mail.beehiiv.com` only | `turingpost.com/p/{slug}` | Beehiiv query unwrap; **not** all Beehiiv senders |

Senders with **no** shape profile keep the legacy generic grouping path (promo boundaries, ambiguity heuristics, optional boundary classifier).

**Not the same as sender profiles (SP1–SP3):** ByteByteGo / ALE / Latent Space use `lookup_sender_profile()` and skip grouping entirely. Every and Turing Post still run the **content-unit** path but with deterministic shape grouping.

---

## Primary URL rules

Implementation: `primary_urls.py`

1. **Unwrap** click-tracking / Beehiiv redirect query params to the destination URL.
2. **Whitelist** story paths via per-profile regex (`story_path_patterns`).
3. **Exclude** chrome paths (`/subscribe`, `/account`, …) and non-article hosts.
4. **Collapse** citations and duplicate links to distinct **canonical story URLs**.
5. **`original_url`** counts as canonical when it matches the profile (Every allows lookup by URL even if sender differs).

Beehiiv unwrap provides the destination URL but does **not** by itself make a link “primary” — the unwrapped host/path must still match the profile whitelist.

---

## Section filters

Implementation: `section_filters.py`

Sections excluded from merge (but may remain in the email for audit):

- Shared teaser/paywall phrases (“become a paid subscriber”, “unlock this piece”, …)
- Short promo sections (`is_promo_section` + `<600` chars)

Excluded keys are recorded on `GroupingResult.digest_excluded_section_keys` and in the persisted shape decision.

---

## Grouping

Implementation: `grouping.py` + `group_content_units()` in `content_unit_grouping.py`

```
lookup profile
  → classify shape
  → filter excluded sections
  → single_article: build_single_article_unit()
  → multi_story: build_multi_story_units() per distinct canonical URL
  → teaser_paywall: units = []
```

**Strong multi-story** (`_strong_multi_story`): requires ≥2 distinct canonical URLs **and** each URL block must have ≥ `min_substantive_article_chars` (default 400). Otherwise downgrade to `single_article`.

---

## Agent integration

In `_process_content_unit_email()` **after** sender-profile fast path is ruled out:

```text
group_content_units(sections, original_url=..., sender=...)
  → persist shape_classifier audit (all shape-profile paths)
  → if teaser_paywall and units empty:
        status = skipped
        return SkippedEmailLink  (no attach_email_to_digest)
  → else: classifier + processor per unit → attach
```

`run_daily()` keeps **`success_links`** (compose + archive) separate from **`skipped_links`** (Gmail label only). An all-skipped run produces an **empty** digest row but still labels processed mail.

---

## Persistence

| Field | Value |
|-------|-------|
| Table | `agent_outputs` |
| `kind` | `shape_classifier` |
| Payload | `NewsletterShapeDecision` (`profile.py`) |

Saved via `StateRepository.save_newsletter_shape_decision()`.

Email statuses:

| Status | Meaning |
|--------|---------|
| `archived` | Attached to a sent digest |
| `skipped` | Shape-profile teaser/paywall — processed, not in digest |

---

## Adding a new profile

1. Define `NewsletterShapeProfile` + `PrimaryUrlRules` in `registry.py`.
2. Register in `NEWSLETTER_SHAPE_PROFILES`.
3. Add fixture JSON under `tests/fixtures/` and grouping tests.
4. Do **not** conflate with sender-profile SP* unless you also want forced category + dedicated processor.

---

## V1 changelog

| Date | Change |
|------|--------|
| 2026-06-16 | Shipped `newsletter_shape` module; Every + Turing Post registry; teaser skip path; production verified (Digest #41 — Turing 18 sections → 1 card). |
