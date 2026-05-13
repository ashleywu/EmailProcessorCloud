# Milestone 4: LLM client, routing, and processor agents

**Prerequisite:** Milestones 1–3 are complete (email ingestion, parsing, storage, Gmail helpers as applicable). Before extending this work, read: `app/models/outputs.py`, `app/models/email.py`, `app/parsing/parser.py`, and `app/config.py` (or their current equivalents).

**Original M4 scope boundary (historical):** Milestone 4 was scoped to the LLM boundary and structured outputs only, not the full daily pipeline. **Current repo:** later work (e.g. Milestone 5) wires these agents into `DailyDigestAgent` and `app/main.py run-daily`. This file still documents what M4 *delivered*; it does not redefine later orchestration specs.

At M4 delivery, the following were explicitly **not** required:

- End-to-end Gmail dispatch / labeling orchestration.
- `DailyDigestAgent` and digest composition (those layers import the M4 pieces).

---

## I. Contract first: `app/models/outputs.py`

Refactor Pydantic models so runtime JSON from the LLM matches the shapes below. Align prompts and tests with these field names.

### 1. `RouteCategory` (unchanged values)

`TECHNOLOGY` | `RADAR` | `LEADERSHIP` | `NOISE`

### 2. `RouterDecision`

| Field | Rule |
|--------|------|
| `category` | One of `RouteCategory` |
| `confidence` | `float`, `0.0`–`1.0` |
| `rationale` | Optional `str` |

### 3. `TechnologyOutput`

| Field | Rule |
|--------|------|
| `core_pain_point` | Required; concise problem statement (not a full-article summary); max length enforced in schema (e.g. ~240 code units as an upper bound for “about 200 Chinese characters”) |
| `diagrams` | List of `Diagram` (`title`, `diagram_type`, `content`) — preserve substantive mermaid/ascii (or similar) from the source; empty list if none |
| `selected_image_urls` | URLs chosen **only** from the parser-supplied candidate list; validation runs when `model_validate` / `model_validate_json` is called with `context={"allowed_image_urls": [...]}` |

### 4. `RadarOutput` / `RadarItem`

| Field | Rule |
|--------|------|
| `items` | List of `RadarItem` with `entity`, `impact_or_action`; optional `url` |
| `summary` | Optional neutral one-liner |

Prompts stress objective, fact-style wording (not enforceable by schema alone).

### 5. `LeadershipOutput` / `LeadershipSignal`

Each signal requires `theme`, `insight`, and **`actionable_item`** (concrete, testable behavior).

### 6. `NoiseOutput`

| Field | Rule |
|--------|------|
| `reason` | Single sentence; no newlines; max length enforced in schema (e.g. 400 chars) |
| `discard` | Boolean (default `true`) |

### 7. Processor output kinds for storage

`PROCESSOR_OUTPUT_KIND` maps each `RouteCategory` to the `agent_outputs.kind` string (`technology`, `radar`, `leadership`, `noise`) so routing and persistence stay aligned.

---

## II. Package layout

```
app/llm/
  __init__.py
  client.py
  providers/
    __init__.py
    openai_provider.py

app/agents/
  __init__.py
  _prompts.py
  router_agent.py
  technology_agent.py
  radar_agent.py
  leadership_agent.py
  noise_agent.py

app/prompts/
  router.md
  technology.md
  radar.md
  leadership.md
  noise.md
```

Agents load markdown prompts from `app/prompts/`; file content must match the JSON field names in `outputs.py`.

---

## III. `LLMClient` (`app/llm/client.py`)

- **Abstract** type with a single public entry point, conceptually:
  - `structured_output(prompt, input_text, response_model, *, model, validation_context=None) -> BaseModel`
- **`response_model`:** any `pydantic` `BaseModel` subclass used for `model_validate_json`.
- **Retry:** On first **JSON decode or Pydantic validation** failure, call the model **once more** with the same system prompt and an augmented user message that includes the error details. **No further retries** for validation.
- **Final failure:** raise **`LLMOutputValidationError`** with access to the last raw text (and validation errors when available).
- **Markdown fences:** tolerate an optional fenced JSON block (e.g. GitHub-style code fences labeled `json`) via a small `extract_json_object_text` helper.

Subclasses implement raw completion (e.g. `_completion_json(system_prompt, user_message, model)`).

---

## IV. `OpenAIProvider` (`app/llm/providers/openai_provider.py`)

- Uses **Chat Completions** with **`response_format={"type": "json_object"}`** and `temperature=0`.
- **Configuration:** callers pass `api_key`, `router_model`, and `processor_model` (see **Configuration** below). The provider does **not** read `os.environ` directly; central settings own env loading.
- **Testability:** accept an injected `OpenAI` client so unit tests never call the real API.

---

## V. Agents

Each agent holds the loaded prompt text and invokes `llm.structured_output` with the correct `response_model` and `model` string (`router_model` vs `processor_model`).

| Agent | Output model | Input notes |
|--------|----------------|-------------|
| `RouterAgent` | `RouterDecision` | `subject` optional; `plain_text` required |
| `TechnologyProcessorAgent` | `TechnologyOutput` | **`ParsedHtmlResult`**: builds user text from `plain_text`, `image_urls` (numbered list), optional `original_url`, optional `subject`; passes `validation_context` with `allowed_image_urls` |
| `RadarProcessorAgent` | `RadarOutput` | Newsletter `subject` + `plain_text` |
| `LeadershipProcessorAgent` | `LeadershipOutput` | Same |
| `NoiseProcessorAgent` | `NoiseOutput` | Same |

`run(..., subject=None, plain_text=...)` style kwargs are acceptable for ergonomics.

---

## VI. Configuration

- **`OPENAI_API_KEY`**, **`ROUTER_MODEL`**, **`PROCESSOR_MODEL`** are defined in **`.env.example`** and loaded through **application settings** (e.g. `pydantic-settings` on a `Settings` class with `env_file_encoding="utf-8"`).
- **`.env`** is **gitignored**; local developers copy from `.env.example` and set a real key for live calls. Tests rely on **mock / scripted** `LLMClient` implementations, not on a key.
- **Combined approach:** secrets and models in `.env` for local use; CI/production inject the same variable names; tests inject a fake client.

---

## VII. Dependencies

- **`openai`** Python SDK (Chat Completions + `json_object` response format).
- **`pydantic`** v2; **`pydantic-settings`** (or equivalent) for `Settings` + `.env`; **`python-dotenv`** may still be used by the settings loader as needed.

---

## VIII. Tests (required)

| Area | Requirement |
|------|----------------|
| Router | Valid JSON parses to `RouterDecision`; invalid `confidence` etc. rejected |
| Processors | Valid JSON parses to each output type; `TechnologyOutput` rejects `selected_image_urls` not in `allowed` when context is provided |
| LLM client | First response invalid JSON or invalid schema, second response valid → success after **two** completion calls |
| LLM client | Two invalid responses → **`LLMOutputValidationError`** |
| OpenAI provider | With a **mock** client, assert `chat.completions.create` is called with the **router** vs **processor** model names as wired |
| Agents | Smoke tests that scripted responses round-trip through each agent |

---

## IX. Acceptance criteria (implemented)

- All fields in §I match `app/prompts/*.md` and `app/models/outputs.py`.
- No hard-coded API keys in the repository.
- `TechnologyProcessorAgent` supplies `allowed_image_urls` from `ParsedHtmlResult.image_urls` so `selected_image_urls` is validated as a subset.
- Full test suite passes without calling the live OpenAI API (mocks / `ScriptedLLMClient`).

Later milestones add digest HTML, quality gates, and Gmail side effects on top of these blocks; see `milestone5.md` for orchestration details.
