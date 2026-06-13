# Technical longform processor (Latent Space profile)

**Status:** SP3 profile fast path — classification is already **TECHNOLOGY**; extract only.

Reply with **only** JSON matching `TechnicalLongformOutput`:

- `title` — article or interview title from the newsletter
- `format` — one of `"interview"`, `"essay"`, `"transcript"`, `"other"` (detect from structure; default to `"essay"` when unclear)
- `central_topic` — one paragraph describing the central technical topic
- `key_technical_insights` — concrete technical insights (strings)
- `architecture_or_workflow_insights` — system design, workflow, or architecture takeaways
- `tradeoffs_or_disagreements` — tradeoffs, disagreements, or contested claims
- `practical_takeaways` — actionable reader takeaways
- `original_url` — copy exactly one HTTPS URL from the candidate list when applicable; otherwise `null`

Treat the entire merged unit as **one** longform — do not split by section headings or Q&A topics.
