# Implementation Status

**Purpose:** Single place to distinguish **what is live** vs **partial** vs **planned**. Design specs may describe future behavior; this file tracks the repo today.

**Status legend:**

| Label | Meaning |
|-------|---------|
| **Implemented** | Shipped, wired in `main.py` or production path, has tests |
| **Partially implemented** | Code or tests exist; orchestration incomplete, not default path, or key deps missing |
| **Planned** | Design doc only; no production wiring |

*Last reviewed: 2026-06-12*

---

## Pipeline paths

| Component | Status | Notes |
|-----------|--------|-------|
| Gmail fetch + parse + sectionizer | **Implemented** | `parse_newsletter_html`, `sectionize_newsletter_html` |
| Section RouterAgent fallback | **Implemented** | Per-section routing when content-unit path off |
| AINews map-reduce Radar | **Implemented** | `MAP_REDUCE_RADAR_SENDERS`, `ainews_radar_digest` |
| Content-unit routing (`enable_content_unit_routing`) | **Partially implemented** | Agents exist; **`daily_digest_agent.py` missing on branch** — verify before deploy |
| `group_content_units` + promo hard boundary | **Partially implemented** | Keyword promo split; no interrupt roles yet |
| Primary links (`primary_links.py`) | **Planned** | P0 design discussed; **file not in repo** — required before `multi_primary_url` fallback |
| Interrupt detection (P1a) | **Planned** | [`interrupt-grouping.md`](interrupt-grouping.md) |
| Generic interrupt bridge (P1b) | **Planned** | Every fallback |
| Boundary classifier (Phase 7) | **Partially implemented** | Agent + tests; trigger/orchestration tuning deferred ([`phase7.1-backlog.md`](phase7.1-backlog.md)) |
| ContentUnitClassifierAgent | **Partially implemented** | Agent + prompts; not primary for profile senders |
| ProcessorDispatcher | **Partially implemented** | Exists; profile-specific processors not added |
| Sender profiles / ProfileExecutor | **Planned** | [`sender-profiles.md`](sender-profiles.md) |
| Sender priors JSON | **Planned** | Referenced in milestone8; not wired |
| `email_processing_decisions` audit table | **Planned** | |

---

## Design documents

| Document | Status |
|----------|--------|
| [`map-reduce-radar-design.md`](map-reduce-radar-design.md) | **Implemented** (matches code) |
| [`section-extraction.md`](section-extraction.md) | **Implemented** |
| [`deploy-vps.md`](deploy-vps.md) | **Implemented** |
| [`interrupt-grouping.md`](interrupt-grouping.md) | **Planned** |
| [`sender-profiles.md`](sender-profiles.md) | **Planned** |
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
| `enable_content_unit_routing=True` in main | Partially implemented — agent file gap |
| Sender prior trust path | Planned |
| All-or-nothing attach on unit failure | Partially implemented |
| Phase 7 boundary classifier | Partially implemented |
| Sender profiles (SP0–SP3) | Planned |
| Turing Post profile (SP4) | Planned — **deferred** until Phase 8 map-reduce |
| LINK_AGGREGATOR map-reduce (Phase 8) | Planned |

See [`milestone8-content-unit-routing.md`](../milestone8-content-unit-routing.md) for full checklist.

---

## V1 profile rollout order

1. **SP1** ByteByteGo — interrupt P1a + `single_tech_article` (no `multi_primary_url` fallback in V1)
2. **SP2** A Life Engineered — `leadership_essay` processor
3. **SP3** Latent Space `swyx@` — `single_tech_longform` processor
4. **SP5** AINews registry entry (refactor only)
5. **Deferred:** Turing Post + generic aggregator map-reduce (Phase 8)
