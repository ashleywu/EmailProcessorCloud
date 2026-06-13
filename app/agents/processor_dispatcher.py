from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from app.agents.courses_agent import CoursesProcessorAgent
from app.agents.leadership_agent import LeadershipProcessorAgent
from app.agents.radar_agent import RadarProcessorAgent
from app.agents.technology_agent import TechnologyProcessorAgent
from app.models.content_units import ContentUnit
from app.models.outputs import PROCESSOR_OUTPUT_KIND, RouteCategory
from app.models.section import EmailSection
from app.parsing.parser import ParsedHtmlResult


@dataclass(frozen=True, slots=True)
class ProcessorDispatchResult:
    kind: str
    output: BaseModel


class ProcessorDispatcher:
    """Deterministic RouteCategory → existing processor agent dispatch."""

    def __init__(
        self,
        *,
        technology_agent: TechnologyProcessorAgent,
        radar_agent: RadarProcessorAgent,
        leadership_agent: LeadershipProcessorAgent,
        courses_agent: CoursesProcessorAgent,
    ) -> None:
        self._technology = technology_agent
        self._radar = radar_agent
        self._leadership = leadership_agent
        self._courses = courses_agent

    def dispatch_section(
        self,
        *,
        category: RouteCategory,
        section: EmailSection,
        subject: str | None,
        parsed_fallback: ParsedHtmlResult | None,
    ) -> ProcessorDispatchResult:
        kind = PROCESSOR_OUTPUT_KIND[category]
        if category == RouteCategory.TECHNOLOGY:
            out = self._technology.run_section(section, subject=subject, parsed_fallback=parsed_fallback)
        elif category == RouteCategory.RADAR:
            out = self._radar.run_section(section, subject=subject)
        elif category == RouteCategory.LEADERSHIP:
            out = self._leadership.run_section(section, subject=subject, parsed_fallback=parsed_fallback)
        elif category == RouteCategory.COURSES:
            out = self._courses.run_section(section, subject=subject, parsed_fallback=parsed_fallback)
        else:
            raise AssertionError(f"unexpected category: {category!r}")
        return ProcessorDispatchResult(kind=kind, output=out)

    def dispatch_unit(
        self,
        *,
        category: RouteCategory,
        unit: ContentUnit,
        subject: str | None,
        parsed_fallback: ParsedHtmlResult | None,
    ) -> ProcessorDispatchResult:
        section = EmailSection(
            section_id=unit.content_unit_key,
            order_index=0,
            heading=unit.headings[0] if unit.headings else None,
            text=unit.unit_text,
            links=list(unit.links),
            image_urls=[],
        )
        return self.dispatch_section(
            category=category,
            section=section,
            subject=subject,
            parsed_fallback=parsed_fallback,
        )


__all__ = ["ProcessorDispatcher", "ProcessorDispatchResult"]
