from __future__ import annotations

from app.agents._prompts import format_section_https_candidates, load_prompt
from app.llm.client import LLMClient
from app.models.outputs import LeadershipSectionOutput
from app.models.section import EmailSection
from app.parsing.parser import ParsedHtmlResult


class LeadershipProcessorAgent:
    """Section-only leadership extractor — no roundup / RSVP fan-out fields."""

    def __init__(self, llm: LLMClient, *, model: str) -> None:
        self._llm = llm
        self._model = model
        self._prompt = load_prompt("leadership_section")

    def run_section(
        self,
        section: EmailSection,
        *,
        subject: str | None = None,
        parsed_fallback: ParsedHtmlResult | None = None,
    ) -> LeadershipSectionOutput:
        original_hint = parsed_fallback.original_url if parsed_fallback is not None else None
        uniq: list[str] = []
        seen: set[str] = set()
        for lst in (section.links, getattr(parsed_fallback, "links", []) if parsed_fallback else []):
            for u in lst or []:
                su = str(u).strip()
                if su.startswith("https://") and su not in seen:
                    seen.add(su)
                    uniq.append(su)
        oz = ""
        if isinstance(original_hint, str):
            oz = original_hint.strip()
            if oz.startswith("https://") and oz not in seen:
                seen.add(oz)
                uniq.insert(0, oz)

        body = format_section_https_candidates(
            subject=subject,
            section_plain_text=section.text,
            heading=section.heading,
            section_links=section.links if section.links else uniq,
            original_url_hint=original_hint,
            link_list_title=(
                "Candidate HTTPS links (`LeadershipSignal.link` must match one entry when populated):"
            ),
        )

        ctx: dict[str, object] = {"allowed_action_urls": uniq}
        return self._llm.structured_output(
            self._prompt,
            body,
            LeadershipSectionOutput,
            model=self._model,
            validation_context=ctx,
        )
