from __future__ import annotations

from app.models.digest import DigestRecord, ProcessedEmail
from app.models.email import EmailInput
from app.models.section import EmailSection
from app.models.outputs import (
    Diagram,
    CourseActionItem,
    CoursePromoBlock,
    CoursesOutput,
    LeadershipColumnOutput,
    LeadershipSectionOutput,
    LeadershipOutput,
    LeadershipSignal,
    PROCESSOR_OUTPUT_KIND,
    RadarItem,
    RadarOutput,
    RouterDecision,
    RouteCategory,
    TechnologyOutput,
    TechnologySectionOutput,
    TechnologyStory,
)

__all__ = [
    "Diagram",
    "DigestRecord",
    "EmailInput",
    "EmailSection",
    "CoursePromoBlock",
    "CoursesOutput",
    "LeadershipColumnOutput",
    "LeadershipSectionOutput",
    "LeadershipSignal",
    "PROCESSOR_OUTPUT_KIND",
    "ProcessedEmail",
    "RadarItem",
    "RadarOutput",
    "RouteCategory",
    "RouterDecision",
    "TechnologySectionOutput",
    "TechnologyStory",
]
