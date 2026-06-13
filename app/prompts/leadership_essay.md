# Leadership essay processor (A Life Engineered profile)

**Status:** SP2 profile fast path — classification is already **LEADERSHIP**; extract only.

Reply with **only** JSON matching `LeadershipEssayOutput`:

- `title` — essay title from the newsletter
- `core_thesis` — one paragraph central thesis
- `leadership_signals` — durable leadership insights (strings)
- `author_action_items` — **only** explicit recommendations the **author** states in the source text (verbatim or tight paraphrase). Do **not** invent items. If the author gives none, return `[]`.
- `senior_engineer_actions` — practical actions **you** derive for a senior engineer reader (may synthesize; clearly actionable)
- `notable_examples` — memorable quotes, stories, or examples from the essay
- `original_url` — copy exactly one HTTPS URL from the candidate list when applicable; otherwise `null`

**Critical:** `author_action_items` and `senior_engineer_actions` serve different audiences — never duplicate the same bullet across both lists.
