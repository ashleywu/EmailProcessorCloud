# Architecture & Engineering Flow

**Status:** **Implemented** (V1 production)  
**Audience:** Design review, onboarding, ops debugging  
**Source of truth:** `app/agents/daily_digest_agent.py`, `app/main.py`, `app/storage/`  
**Related:** [`pipeline-flowchart.md`](pipeline-flowchart.md), [`mixed-newsletter-shape-profile.md`](mixed-newsletter-shape-profile.md), [`sender-profiles.md`](sender-profiles.md)

This document is the **visual companion** to the step-by-step pipeline flowchart. It shows (1) layered system architecture, (2) how routing strategies overlap, and (3) the engineering lifecycle from cron to Gmail.

---

## 1. Layered system architecture

```mermaid
flowchart TB
    subgraph DELIVER["Delivery & ops"]
        Cron["cron / scripts/run-daily.sh"]
        CLI["python -m app.main run-daily"]
        Env[".env + Settings"]
    end

    subgraph INGRESS["Ingress — Gmail"]
        Fetch["GmailFetcher.fetch_recent()"]
        Upsert["StateRepository.upsert_email()"]
        Label["GmailLabeler — PROCESSED / INBOX"]
        Send["GmailSender.send_html()"]
    end

    subgraph ORCH["Orchestration"]
        Lock["RunLock — single-flight"]
        Agent["DailyDigestAgent.run_daily()"]
        QG["DigestQualityGateAgent"]
    end

    subgraph PARSE["Parse & structure"]
        HTML["parse_newsletter_html()"]
        Sec["sectionizer → EmailSection[]"]
        Caps["normalize_sections_for_routing()"]
        Intr["interrupt_detection — P1a"]
    end

    subgraph ROUTE["Routing — first match wins"]
        MR["AINews map-reduce Radar"]
        SP["Sender profile SP1–SP3"]
        Shape["Newsletter shape profile"]
        Gen["Generic content-unit + BC"]
        Leg["Legacy section RouterAgent"]
    end

    subgraph AGENTS["LLM agents & processors"]
        CUCls["ContentUnitClassifierAgent"]
        BC["BoundaryClassifierAgent"]
        Disp["ProcessorDispatcher"]
        Proc["technology / radar / leadership / courses / …"]
    end

    subgraph COMPOSE["Compose"]
        Comp["DigestComposer + Jinja template"]
    end

    subgraph PERSIST["Persistence — SQLite"]
        DB[("daily_digest.db")]
        Emails["emails"]
        Sections["email_sections"]
        Outputs["agent_outputs"]
        Digests["digests + digest_emails"]
    end

    subgraph EXT["External"]
        Gmail[(Gmail API)]
        OAI[(OpenAI API)]
    end

    Cron --> CLI
    Env --> CLI
    CLI --> Lock
    Lock --> Agent
    Agent --> Fetch
    Fetch --> Gmail
    Fetch --> Upsert
    Upsert --> Emails
    Agent --> HTML
    HTML --> Sec
    Sec --> Caps
    Caps --> Sections
    Agent --> MR
    Agent --> SP
    Agent --> Shape
    Agent --> Gen
    Agent --> Leg
    SP --> Intr
    Shape --> Gen
    Gen --> CUCls
    Gen --> BC
    CUCls --> Disp
    BC --> Disp
    SP --> Proc
    MR --> Proc
    Disp --> Proc
    Proc --> OAI
    Proc --> Outputs
    Agent --> Comp
    Comp --> QG
    QG --> Send
    Send --> Gmail
    Agent --> Label
    Agent --> Digests
    Emails --> DB
    Sections --> DB
    Outputs --> DB
    Digests --> DB
```

**Dependency rule:** Orchestration calls everything else; routing modules never call Gmail directly except through injected collaborators.

---

## 2. Routing strategy overlap (Venn view)

Four **mutually ordered** strategies handle incoming mail. A sender belongs to **at most one primary path** per run; shape profile and generic grouping only apply **inside** the content-unit branch.

```mermaid
flowchart LR
    subgraph UNIVERSE["All newsletter candidates in SQLite (pending / retryable)"]
        direction TB
        A["AINews swyx+ainews@"]
        B["SP1 ByteByteGo · SP2 ALE · SP3 Latent swyx@"]
        C["Every hello@every.to · Turing turingpost@mail.beehiiv.com"]
        D["Unknown / fallback senders"]
    end

    subgraph P_MR["Map-reduce Radar"]
        MRbox["Whole-email Radar digest<br/>kind=ainews_radar_digest"]
    end

    subgraph P_SP["Sender profile fast path"]
        SPbox["Strip interrupts → merge → forced category<br/>1 processor · 1 card"]
    end

    subgraph P_SHAPE["Shape profile (inside content-unit)"]
        SHbox["Deterministic merge / split / skip teaser<br/>kind=shape_classifier audit"]
    end

    subgraph P_GEN["Generic content-unit"]
        GEbox["Promo boundaries · ambiguity · BC<br/>per-unit classifier + processor"]
    end

    A --> MRbox
    B --> SPbox
    C --> SHbox
    SHbox --> GEbox
    D --> GEbox
    SPbox -.->|counter-evidence| GEbox
```

| Set | Members (V1) | Classifier? | Typical cards |
|-----|----------------|-------------|---------------|
| **Map-reduce** | AINews | No (fixed Radar) | 1 Radar digest |
| **Sender profile** | ByteByteGo, ALE, Latent `swyx@` | No on happy path | 1 |
| **Shape + content-unit** | Every, Turing Post | Yes (per unit) | 1 (merged) |
| **Generic content-unit** | Everyone else; profile fallback | Yes | 1…N |

**Overlap clarification (not Venn intersections in production):**

- **Sender profile ∩ Shape profile** = ∅ (different senders today).
- **Shape profile ⊂ Content-unit path** — shape runs *before* classifier inside `_process_content_unit_email`.
- **Sender profile → Generic** only on structural counter-evidence (`promo_dominated`, `empty_body`).

---

## 3. Per-email decision tree (engineering logic)

```mermaid
flowchart TD
    E([Email candidate]) --> R0{Cached complete outputs?}
    R0 -->|yes| Reuse[attach + return ProcessLink]
    R0 -->|no| R1{Map-reduce sender?}
    R1 -->|yes| MR[Map-reduce agent → Radar output]
    R1 -->|no| R2{content_unit_routing?}
    R2 -->|no| Legacy[Per-section RouterAgent loop]
    R2 -->|yes| R3{Sender profile match?}
    R3 -->|yes| R3a{Counter-evidence?}
    R3a -->|no| SP[Profile executor → 1 unit]
    R3a -->|yes| Generic
    R3 -->|no| Generic[group_content_units]
    Generic --> R4{Shape profile?}
    R4 -->|every_to / turing_post| R5{classify shape}
    R4 -->|none| R6{ambiguous?}
    R5 -->|teaser_paywall| Skip[SkippedEmailLink · status=skipped]
    R5 -->|single / multi| Units[Build ContentUnit list]
    R6 -->|yes| BC[BoundaryClassifier optional]
    R6 -->|no| Units
    BC --> Units
    Units --> Loop[For each unit: classify → process]
    MR --> Attach[attach_email_to_digest]
    SP --> Attach
    Legacy --> Attach
    Loop --> Attach
    Reuse --> Done([Done for this email])
    Attach --> Done
    Skip --> DoneSkip([Done — not in digest])
```

---

## 4. Data & cache flow

```mermaid
flowchart LR
    subgraph WRITE["Write path (per email)"]
        W1[replace_email_sections]
        W2[save_agent_output]
        W3[attach_email_to_digest]
    end

    subgraph READ["Read path (compose)"]
        R1[get_outputs_by_email_ids]
        R2[DigestComposer]
    end

    W1 --> ES[(email_sections)]
    W2 --> AO[(agent_outputs)]
    W3 --> DE[(digest_emails)]
    AO --> R1
    R1 --> R2
    R2 --> DH[(digests.body_html)]

    subgraph KINDS["agent_outputs.kind (examples)"]
        K1[shape_classifier]
        K2[classifier]
        K3[technology · radar · leadership · courses]
        K4[ainews_radar_digest]
        K5[boundary_classifier]
    end

    AO --- KINDS
```

**Cache hit:** `try_reuse_complete_outputs` / `profile_unit_outputs_cached` skips LLM when section hashes and output kinds align.

**Force reprocess:** `DELETE FROM agent_outputs WHERE email_id=?` + `UPDATE emails SET status='pending'`.

---

## 5. Engineering lifecycle (dev → prod)

```mermaid
flowchart TB
    subgraph DEV["Development"]
        Code["app/ — agents, parsing, processing, digest"]
        Tests["pytest tests/"]
        Fixtures["tests/fixtures/*.json"]
    end

    subgraph CONFIG["Configuration"]
        DotEnv[".env — senders, API keys, DB path"]
        Secrets["secrets/credentials.json + token.json"]
    end

    subgraph DEPLOY["Deploy — VPS"]
        Git["git pull main"]
        Venv[".venv + pip install -e .[gmail]"]
        CronE["cron → scripts/run-daily.sh"]
        Log["logs/run-daily-YYYY-MM.log"]
    end

    subgraph RUN["Daily execution"]
        Ingest["Gmail list + upsert"]
        Pipe["DailyDigestAgent"]
        Out["Digest email + labels"]
    end

    subgraph OBSERVE["Observe & debug"]
        Preview["preview-digest --date YYYY-MM-DD"]
        ShowCfg["show-config"]
        SQL["sqlite3 daily_digest.db"]
        Audit["agent_outputs payloads"]
    end

    Code --> Tests
    Fixtures --> Tests
    Code --> Git
    DotEnv --> CronE
    Secrets --> CronE
    Git --> Venv
    Venv --> CronE
    CronE --> Log
    CronE --> Ingest
    Ingest --> Pipe
    Pipe --> Out
    Pipe --> Audit
    SQL --> Audit
    Preview --> SQL
    ShowCfg --> DotEnv
```

| Stage | Command / artifact |
|-------|-------------------|
| Local test | `pytest tests/test_newsletter_shape_profile.py` |
| Manual run | `python -m app.main run-daily` |
| Prod schedule | `0 17 * * * …/scripts/run-daily.sh` |
| Inspect digest | `python -m app.main preview-digest --date 2026-06-16` |
| Clear stale cache | Delete `agent_outputs` for `email_id`, set `status=pending` |

---

## 6. Module map (code ↔ concern)

```mermaid
mindmap
  root((daily-digest))
    Gmail
      fetcher
      labeler
      sender
      client
    Orchestration
      daily_digest_agent
      main CLI
      run_lock
    Parsing
      parser sectionizer
      content_unit_grouping
      interrupt_detection
      boundary_validation
    Processing
      sender_profiles
      profile_executor
      newsletter_shape
      unit_classification
      confidence_band
    Agents
      map_reduce_radar
      content_unit_classifier
      boundary_classifier
      processor_dispatcher
      technology radar leadership courses
    Digest
      composer
      quality_gate
      templates
    Storage
      repository
      db schema
```

---

## 7. Digest output structure (downstream)

```mermaid
flowchart TB
    subgraph HTML["Final HTML email"]
        H[Header + date]
        T[Technical Index section]
        R[AI Radar section]
        L[Leadership section]
        C[Courses section]
    end

    Comp[DigestComposer] --> H
    Comp --> T
    Comp --> R
    Comp --> L
    Comp --> C

    T --> Card1["Card: title · pain point · URL · diagrams"]
    R --> Card2["Card(s)"]
    L --> Card3["Card(s)"]
    C --> Card4["Card(s)"]

    AO[(agent_outputs rows)] --> Comp
```

Each **card** maps to one `(email_id, content_unit_key)` processor row (or map-reduce digest row for AINews).

---

## 8. Changelog

| Date | Change |
|------|--------|
| 2026-06-16 | Initial architecture + Venn-style routing overlap + engineering lifecycle |
