# Design documentation index

**Status legend:** **Implemented** · **Partially implemented** · **Planned** — definitions in [`implementation-status.md`](implementation-status.md).

| Document | Status | Summary |
|----------|--------|---------|
| [`implementation-status.md`](implementation-status.md) | Living doc | What is live vs partial vs planned in the repo |
| [`mixed-newsletter-shape-profile.md`](mixed-newsletter-shape-profile.md) | **Implemented** | Every + Turing Post shape grouping (merge / skip teaser) |
| [`pipeline-flowchart.md`](pipeline-flowchart.md) | **Implemented** | End-to-end `DailyDigestAgent` flow (Mermaid) |
| [`sender-profiles.md`](sender-profiles.md) | **Partially implemented** | SP1–SP3 fast path; Every/Turing use shape profile instead |
| [`interrupt-grouping.md`](interrupt-grouping.md) | **Planned** | Shared interrupt detection; generic bridge for fallback |
| [`map-reduce-radar-design.md`](map-reduce-radar-design.md) | **Implemented** | AINews map-reduce Radar |
| [`section-extraction.md`](section-extraction.md) | **Implemented** | DOM sectionizer, links per slice |
| [`deploy-vps.md`](deploy-vps.md) | **Implemented** | Ubuntu VPS + cron |
| [`phase7.1-backlog.md`](phase7.1-backlog.md) | **Planned** | Phase 7 ambiguous-trigger tightening |

**Implementation specs (repo root):**

| Milestone | Status | Topic |
|-----------|--------|--------|
| [`milestone5.md`](../milestone5.md) | **Implemented** | Section pipeline (RouterAgent path) |
| [`milestone8-content-unit-routing.md`](../milestone8-content-unit-routing.md) | **Partially implemented** | Content-unit agents; orchestration incomplete |

**Prompts:** [`app/prompts/README.md`](../app/prompts/README.md)

**Removed / superseded:** `content-unit-classifiers.md`, `content-unit-routing-design.md` — see implementation-status.
