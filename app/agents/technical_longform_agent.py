from __future__ import annotations

from app.agents._prompts import format_content_unit_classifier_input, load_prompt
from app.llm.client import LLMClient
from app.models.content_units import ContentUnit
from app.models.outputs import TechnicalLongformOutput
from app.parsing.link_extractor import article_link_candidates
from app.parsing.parser import ParsedHtmlResult


class TechnicalLongformProcessorAgent:
    """Profile SP3 — extract one merged Latent Space tech longform (`TechnicalLongformOutput`)."""

    def __init__(self, llm: LLMClient, *, model: str) -> None:
        self._llm = llm
        self._model = model
        self._prompt = load_prompt("technical_longform")

    def run_unit(
        self,
        unit: ContentUnit,
        *,
        subject: str | None = None,
        parsed_fallback: ParsedHtmlResult | None = None,
    ) -> TechnicalLongformOutput:
        original_hint = parsed_fallback.original_url if parsed_fallback is not None else None
        article_candidates = article_link_candidates(unit.links)
        if parsed_fallback is not None:
            for url in article_link_candidates(parsed_fallback.links):
                if url not in article_candidates:
                    article_candidates.append(url)
        if isinstance(original_hint, str):
            hint = original_hint.strip()
            if hint.startswith("https://") and hint not in article_candidates:
                article_candidates.insert(0, hint)

        title = unit.headings[0] if unit.headings else unit.content_unit_key
        body = format_content_unit_classifier_input(
            subject=subject,
            unit_title=title,
            headings=unit.headings,
            plain_text=unit.unit_text,
            links=unit.links,
        )
        ctx: dict[str, object] = {"allowed_article_urls": article_candidates}
        out = self._llm.structured_output(
            self._prompt,
            body,
            TechnicalLongformOutput,
            model=self._model,
            validation_context=ctx,
        )
        if out.original_url not in set(article_candidates) and len(article_candidates) == 1:
            return out.model_copy(update={"original_url": article_candidates[0]})
        return out


__all__ = ["TechnicalLongformProcessorAgent"]
