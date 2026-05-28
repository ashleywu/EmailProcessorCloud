from __future__ import annotations

from app.agents._prompts import format_section_https_candidates, load_prompt
from app.llm.client import LLMClient
from app.models.outputs import TechnologySectionOutput
from app.models.section import EmailSection
from app.parsing.link_extractor import article_link_candidates
from app.parsing.parser import ParsedHtmlResult


class TechnologyProcessorAgent:
    """Section-scoped technology extraction (`TechnologySectionOutput`)."""

    def __init__(self, llm: LLMClient, *, model: str) -> None:
        self._llm = llm
        self._model = model
        self._prompt = load_prompt("technology_section")

    def run_section(
        self,
        section: EmailSection,
        *,
        subject: str | None = None,
        parsed_fallback: ParsedHtmlResult | None = None,
    ) -> TechnologySectionOutput:
        original_hint = parsed_fallback.original_url if parsed_fallback is not None else None
        fallback_links = list(parsed_fallback.links) if parsed_fallback is not None else []
        article_candidates = article_link_candidates(section.links)
        if fallback_links:
            for u in article_link_candidates(fallback_links):
                if u not in article_candidates:
                    article_candidates.append(u)

        if isinstance(original_hint, str):
            zs = original_hint.strip()
            if zs.startswith("https://") and zs not in article_candidates:
                article_candidates.insert(0, zs)

        body = format_section_https_candidates(
            subject=subject,
            section_plain_text=section.text,
            heading=section.heading,
            section_links=section.links,
            original_url_hint=original_hint,
            link_list_title=(
                "Candidate article / original HTTPS URLs (`original_url` must copy exactly one URL from here):"
            ),
        )

        ctx: dict[str, object] = {"allowed_article_urls": article_candidates}
        out = self._llm.structured_output(
            self._prompt,
            body,
            TechnologySectionOutput,
            model=self._model,
            validation_context=ctx,
        )
        return _repair_original_url(section, parsed_fallback, article_candidates, out)


def _repair_original_url(
    section: EmailSection,
    parsed_fallback: ParsedHtmlResult | None,
    article_candidates: list[str],
    out: TechnologySectionOutput,
) -> TechnologySectionOutput:
    """Fallback when validator context was empty in tests."""

    cand = article_candidates[:] if article_candidates else []

    oh = getattr(parsed_fallback, "original_url", None) if parsed_fallback is not None else None
    if isinstance(oh, str):
        zs = oh.strip()
        if zs.startswith("https://"):
            cand = [zs, *[u for u in cand if u != zs]]

    for lk in section.links:
        ls = str(lk).strip()
        if ls.startswith("https://") and ls not in cand:
            cand.append(ls)

    if out.original_url not in cand and len(cand) == 1:
        return out.model_copy(update={"original_url": cand[0]})

    allowed = set(cand)
    if out.original_url in allowed:
        return out

    fallback = cand[0] if len(cand) == 1 else None
    if fallback is None and parsed_fallback is not None and parsed_fallback.links:
        for u in article_link_candidates(parsed_fallback.links):
            if u in allowed:
                fallback = u
                break

    return out.model_copy(update={"original_url": fallback or out.original_url})
