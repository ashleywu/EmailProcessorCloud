from __future__ import annotations

from app.agents._prompts import format_content_unit_classifier_input, load_prompt
from app.llm.client import LLMClient
from app.models.content_units import (
    ClassificationRoutingSource,
    ContentUnit,
    ContentUnitClassificationResult,
    ContentUnitClassifierLLMOutput,
)


class ContentUnitClassifierAgent:
    """LLM classifier for one grouped content unit (Phase 6 path)."""

    def __init__(self, llm: LLMClient, *, model: str) -> None:
        self._llm = llm
        self._model = model
        self._prompt = load_prompt("content_unit_classifier")

    def classify(
        self,
        *,
        unit: ContentUnit,
        subject: str | None = None,
        outline: object | None = None,
        prior: object | None = None,
        sanity: object | None = None,
        parsed: object | None = None,
    ) -> ContentUnitClassificationResult:
        del outline, prior, sanity, parsed
        title = unit.headings[0] if unit.headings else unit.content_unit_key
        body = format_content_unit_classifier_input(
            subject=subject,
            unit_title=title,
            headings=unit.headings,
            plain_text=unit.unit_text,
            links=unit.links,
        )
        out = self._llm.structured_output(
            self._prompt,
            body,
            ContentUnitClassifierLLMOutput,
            model=self._model,
        )
        return ContentUnitClassificationResult(
            category=out.category,
            confidence=out.confidence,
            rationale=out.rationale,
            primary_value=out.primary_value,
            evidence=out.evidence,
            routing_source=ClassificationRoutingSource.LLM_CLASSIFIER,
        )


__all__ = ["ContentUnitClassifierAgent"]
