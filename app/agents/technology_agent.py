from __future__ import annotations

from app.agents._prompts import load_prompt
from app.llm.client import LLMClient
from app.models.outputs import TechnologyOutput, TechnologyStory
from app.parsing.link_extractor import article_link_candidates
from app.parsing.parser import ParsedHtmlResult


def format_technology_input(parsed: ParsedHtmlResult, *, subject: str | None = None) -> str:
    blocks: list[str] = []
    if subject:
        blocks.append(f"Subject: {subject}")
    if parsed.original_url:
        blocks.append(f"Original URL (hint): {parsed.original_url}")

    article_urls = article_link_candidates(parsed.links)
    lines_article = ["Candidate article URLs (for ``stories[].article_url`` only — copy exactly, one per story):"]
    for i, url in enumerate(article_urls, start=1):
        lines_article.append(f"  {i}. {url}")
    blocks.append("\n".join(lines_article))

    blocks.append("Plain text:\n" + parsed.plain_text)

    lines_img = ["Candidate image_urls (illustration only; not for ``article_url``) — select zero or more, copy exactly:"]
    for i, url in enumerate(parsed.image_urls, start=1):
        lines_img.append(f"  {i}. {url}")
    blocks.append("\n".join(lines_img))
    return "\n\n".join(blocks)


def _enrich_technology_output(
    parsed: ParsedHtmlResult,
    article_urls: list[str],
    output: TechnologyOutput,
) -> TechnologyOutput:
    """Attach digest fallback URL and repair obvious bad ``article_url`` values when allowlists were empty."""

    primary = parsed.original_url or (article_urls[0] if article_urls else None)
    allowed = set(article_urls) if article_urls else None
    known = set(parsed.links)
    if primary:
        known.add(primary)
    single_story = len(output.stories) <= 1

    def repair_url(u: str) -> str:
        u = (u or "").strip()
        if not u.startswith(("http://", "https://")):
            return primary or u
        if allowed is not None:
            return u
        if primary and single_story and u not in known:
            return primary
        return u

    fixed = [
        TechnologyStory(
            title=s.title,
            article_url=repair_url(s.article_url),
            summary=s.summary,
        )
        for s in output.stories
    ]
    return output.model_copy(update={"stories": fixed, "digest_source_url": primary})


class TechnologyProcessorAgent:
    def __init__(self, llm: LLMClient, *, model: str) -> None:
        self._llm = llm
        self._model = model
        self._prompt = load_prompt("technology")

    def run(self, parsed: ParsedHtmlResult, *, subject: str | None = None) -> TechnologyOutput:
        body = format_technology_input(parsed, subject=subject)
        article_urls = article_link_candidates(parsed.links)
        if parsed.original_url and parsed.original_url not in article_urls:
            article_urls = [parsed.original_url, *article_urls]
        ctx: dict[str, object] = {"allowed_image_urls": list(parsed.image_urls)}
        if article_urls:
            ctx["allowed_article_urls"] = article_urls
        out = self._llm.structured_output(
            self._prompt,
            body,
            TechnologyOutput,
            model=self._model,
            validation_context=ctx,
        )
        return _enrich_technology_output(parsed, article_urls, out)
