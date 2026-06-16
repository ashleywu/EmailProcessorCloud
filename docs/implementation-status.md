# Implementation Status

**Purpose:** Single place to distinguish **what is live** vs **partial** vs **planned**. Design specs may describe future behavior; this file tracks the repo today.

**Status legend:**

| Label | Meaning |
|-------|---------|
| **Implemented** | Shipped, wired in `main.py` or production path, has tests |
| **Partially implemented** | Code or tests exist; orchestration incomplete, not default path, or key deps missing |
| **Planned** | Design doc only; no production wiring |

*Last reviewed: 2026-06-16 (newsletter shape profile V1)*

---

## Pipeline paths

| Component | Status | Notes |
|-----------|--------|-------|
| Gmail fetch + parse + sectionizer | **Implemented** | `parse_newsletter_html`, `sectionize_newsletter_html` |
| Section RouterAgent fallback | **Implemented** | Per-section routing when content-unit path off |
| AINews map-reduce Radar | **Implemented** | `MAP_REDUCE_RADAR_SENDERS`, `ainews_radar_digest` |
| Content-unit routing (`enable_content_unit_routing`) | **Implemented** | Wired in `main.py` + `daily_digest_agent.py` |
| **Newsletter shape profiles** | **Implemented** | `app/processing/newsletter_shape/` — Every + Turing Post; [`mixed-newsletter-shape-profile.md`](mixed-newsletter-shape-profile.md) |
| `group_content_units` + promo hard boundary | **Implemented** | Shape path for Every/Turing; legacy heuristics + optional BC for others |
| Primary URL normalization | **Implemented** | Profile-driven in `newsletter_shape/primary_urls.py` |
| Interrupt detection (P1a) | **Implemented** | `interrupt_detection.py`; used by profile fast path |
| Generic interrupt bridge (P1b) | **Planned** | Every fallback only — unchanged |
| Boundary classifier (Phase 7) | **Partially implemented** | Agent + tests; generic ambiguous grouping only ([`phase7.1-backlog.md`](phase7.1-backlog.md)) |
| ContentUnitClassifierAgent | **Partially implemented** | Shape-profile + generic paths; skipped for sender-profile SP1–SP3 |
| ProcessorDispatcher | **Implemented** | Generic units + SP1 `technology` dispatch |
| **Sender profiles SP1–SP3** | **Implemented / Frozen** | ByteByteGo, A Life Engineered, Latent Space `swyx@` — see [`sender-profiles.md`](sender-profiles.md) |
| Sender priors JSON | **Planned** | Referenced in milestone8; not wired |
| `email_processing_decisions` audit table | **Planned** | Profile audit via `kind=classifier` rows + `app/audit/profile_email.py` |
| Shape audit (`kind=shape_classifier`) | **Implemented** | `NewsletterShapeDecision` persisted per shape-profile email |

---

## Design documents

| Document | Status |
|----------|--------|
| [`map-reduce-radar-design.md`](map-reduce-radar-design.md) | **Implemented** (matches code) |
| [`section-extraction.md`](section-extraction.md) | **Implemented** |
| [`deploy-vps.md`](deploy-vps.md) | **Implemented** |
| [`interrupt-grouping.md`](interrupt-grouping.md) | **Partially implemented** | P1a live for profiles; P1b generic bridge planned |
| [`sender-profiles.md`](sender-profiles.md) | **Partially implemented** | SP1–SP3 frozen; Every/Turing use **shape profile** (not SP4) |
| [`mixed-newsletter-shape-profile.md`](mixed-newsletter-shape-profile.md) | **Implemented** |
| [`pipeline-flowchart.md`](pipeline-flowchart.md) | **Implemented** |
| [`architecture-diagram.md`](architecture-diagram.md) | **Implemented** |
| [`phase7.1-backlog.md`](phase7.1-backlog.md) | **Planned** |
| `content-unit-classifiers.md` | **Removed** — policies split into milestone8 + sender-profiles + interrupt-grouping |
| `content-unit-routing-design.md` | **Removed** — superseded by docs above |

---

## Milestone 8 checklist (granular)

| Item | Status |
|------|--------|
| `ContentUnitClassifierAgent` | Partially implemented |
| `ProcessorDispatcher` | Partially implemented |
| `confidence_band` | Partially implemented |
| Composer `(email_id, content_unit_key)` pair join | Partially implemented |
| `enable_content_unit_routing=True` in main | **Implemented** |
| Sender prior trust path | Planned |
| All-or-nothing attach on unit failure | **Implemented** (profile + generic) |
| Phase 7 boundary classifier | Partially implemented |
| Sender profiles SP1–SP3 | **Implemented / Frozen** |
| Sender profile SP4 (Turing Post forced category) | **Deferred** — Phase 8 map-reduce dependency |
| Newsletter shape `turing_post` | **Implemented** — merge/skip via [`mixed-newsletter-shape-profile.md`](mixed-newsletter-shape-profile.md) |
| LINK_AGGREGATOR map-reduce (Phase 8) | Planned |

See [`milestone8-content-unit-routing.md`](../milestone8-content-unit-routing.md) for full checklist.

---

## V1 executive decisions (locked)

See [`sender-profiles.md`](sender-profiles.md) § V1 executive decisions.

1. **`UNKNOWN_INTERRUPT` retained in article** — never hidden.
2. **Profile SP1 (ByteByteGo)** — P1a interrupt detection only; **no** bridge, **no** BC prerequisite.
3. **Structural counter-evidence only → generic fallback**; processor failure → fail + retry same profile.

## V1 profile rollout order

| Profile | Status |
|---------|--------|
| **SP1** ByteByteGo | **Implemented / Frozen** |
| **SP2** A Life Engineered | **Implemented / Frozen** |
| **SP3** Latent Space `swyx@` | **Implemented / Frozen** |
| **SP4** Turing Post (sender profile) | **Deferred** (Phase 8) |
| **Shape** Every + Turing Post | **Implemented** — see [`mixed-newsletter-shape-profile.md`](mixed-newsletter-shape-profile.md) |
| P1b generic interrupt bridge | **Planned** — Every fallback only |
| AINews map-reduce | **Implemented / Frozen** — do not change |

## Profile fast-path contract (SP1–SP3)

```
known profile → strip strippable interrupts → merge article body → forced category
→ one processor call → one digest card
```

| Rule | Behavior |
|------|----------|
| Structural counter-evidence | `promo_dominated`, `empty_body` → generic pipeline |
| Processor / schema failure | Fail email; retry **same profile** — never generic fallback |
| Cache reuse | After parse + `replace_email_sections`, reuse when `kind=classifier` row has matching `content_hash` + processor output exists |
| Invalidation | Retained section `content_hash` change → merged hash changes → processor reruns |
| Strippable-only change | Merged hash stable → processor output may be reused |
| Audit | `agent_outputs` `kind=classifier` with `routing_source=sender_profile`, `sender_profile`, `grouping_strategy`, `content_hash`, `processor_kind` |

See [`sender-profiles.md`](sender-profiles.md) for per-profile rules.
