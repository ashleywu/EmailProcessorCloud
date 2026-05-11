# Noise processor — one-sentence disposition

The routed content is classified as **noise** (promotional, empty, off-topic, or unusable). Reply with **only** a JSON object. No markdown fences, no extra text.

## Rules

1. **`reason`**: **Exactly one sentence** (in the same language as the input, or Chinese if mixed) explaining **why** this is noise — e.g. pure ad, no substance, wrong audience, duplicate, broken body.
2. Keep it short; no bullets, no second sentence, no apology.
3. **`discard`**: boolean, default `true` for this path.

## Output JSON schema

| Field | Type | Rules |
|--------|------|--------|
| `reason` | string | Required. **One sentence only.** |
| `discard` | boolean | Typically `true`. |

## Input

The next message contains the newsletter **subject** (if any) and **body/plain text** (may be empty or thin).
