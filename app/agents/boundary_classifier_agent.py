"""Phase 7 LLM boundary classifier.

Receives a structural outline of the ambiguous non-promo sections of an email and
returns a grouping proposal (``BoundaryLLMOutput``).  The caller is responsible for
validation, fallback, and building canonical ``ContentUnit`` objects.
"""

from __future__ import annotations

from app.agents._prompts import format_boundary_classifier_input, load_prompt
from app.llm.client import LLMClient
from app.models.content_units import (
    BoundaryLLMOutput,
    BoundaryOutlineSection,
    GroupingAmbiguityReason,
)
from app.models.content_units import ContentUnit


class BoundaryClassifierAgent:
    """LLM boundary classifier for ambiguous newsletter section grouping (Phase 7).

    Only invoked when ``GroupingResult.ambiguous=True``.  Never invoked for
    AINews / MAP_REDUCE_RADAR_SENDERS emails or for category classification.
    """

    def __init__(self, llm: LLMClient, *, model: str) -> None:
        self._llm = llm
        self._model = model
        self._prompt = load_prompt("boundary_classifier")

    def classify_boundaries(
        self,
        *,
        sender: str | None,
        subject: str | None,
        original_url: str | None,
        sections: list[BoundaryOutlineSection],
        deterministic_units: list[ContentUnit],
        ambiguity_reasons: list[GroupingAmbiguityReason],
        hard_boundary_section_keys: list[str] | None = None,
    ) -> BoundaryLLMOutput:
        """Call the LLM and return the raw output.

        May raise any exception (network error, JSON parse error, Pydantic
        ``ValidationError``, etc.).  The caller (``DailyDigestAgent._run_boundary_classifier``)
        catches all exceptions and falls back to conservative units.
        """
        body = format_boundary_classifier_input(
            sender=sender,
            subject=subject,
            original_url=original_url,
            sections=sections,
            deterministic_units=deterministic_units,
            ambiguity_reasons=ambiguity_reasons,
            hard_boundary_section_keys=hard_boundary_section_keys,
        )
        return self._llm.structured_output(
            self._prompt,
            body,
            BoundaryLLMOutput,
            model=self._model,
        )


__all__ = ["BoundaryClassifierAgent"]
