from __future__ import annotations

from app.agents._prompts import (
    format_section_https_candidates,
    format_subject_plain_https_link_candidates,
    load_prompt,
)
from app.llm.client import LLMClient
from app.models.outputs import CoursesOutput
from app.models.section import EmailSection
from app.parsing.parser import ParsedHtmlResult


class CoursesProcessorAgent:
    def __init__(self, llm: LLMClient, *, model: str) -> None:
        self._llm = llm
        self._model = model
        self._prompt = load_prompt("courses")

    def run(self, parsed: ParsedHtmlResult, *, subject: str | None = None) -> CoursesOutput:
        body = format_subject_plain_https_link_candidates(
            subject=subject,
            parsed=parsed,
            link_list_title="Candidate links (HTTPS only — copy exactly for courses.actions[].url):",
        )
        allowed_links: list[str] = []
        seen: set[str] = set()
        for u in parsed.links:
            su = str(u).strip()
            if su.startswith("https://") and su not in seen:
                seen.add(su)
                allowed_links.append(su)
        ou = parsed.original_url
        if isinstance(ou, str) and ou.strip().startswith("https://"):
            hz = ou.strip()
            if hz not in seen:
                seen.add(hz)
                allowed_links.insert(0, hz)

        ctx: dict[str, object] = {"allowed_action_urls": allowed_links}

        return self._llm.structured_output(
            self._prompt,
            body,
            CoursesOutput,
            model=self._model,
            validation_context=ctx,
        )

    def run_section(
        self,
        section: EmailSection,
        *,
        subject: str | None = None,
        parsed_fallback: ParsedHtmlResult | None = None,
    ) -> CoursesOutput:
        oh = parsed_fallback.original_url if parsed_fallback is not None else None

        uniq: list[str] = []
        seen: set[str] = set()
        for lst in (section.links, getattr(parsed_fallback, "links", []) if parsed_fallback else []):
            for u in lst or []:
                su = str(u).strip()
                if su.startswith("https://") and su not in seen:
                    seen.add(su)
                    uniq.append(su)
        if isinstance(oh, str):
            zs = oh.strip()
            if zs.startswith("https://") and zs not in seen:
                seen.add(zs)
                uniq.insert(0, zs)

        body = format_section_https_candidates(
            subject=subject,
            section_plain_text=section.text,
            heading=section.heading,
            section_links=section.links if section.links else uniq,
            original_url_hint=oh,
            link_list_title="Candidate HTTPS links (`actions` / promo CTAs — copy verbatim):",
        )

        ctx: dict[str, object] = {"allowed_action_urls": uniq}

        return self._llm.structured_output(
            self._prompt,
            body,
            CoursesOutput,
            model=self._model,
            validation_context=ctx,
        )
