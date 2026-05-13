from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


class RouteCategory(StrEnum):
    TECHNOLOGY = "TECHNOLOGY"
    RADAR = "RADAR"
    LEADERSHIP = "LEADERSHIP"
    NOISE = "NOISE"


# Persisted ``agent_outputs.kind`` for each router category (single source of truth).
PROCESSOR_OUTPUT_KIND: dict[RouteCategory, str] = {
    RouteCategory.TECHNOLOGY: "technology",
    RouteCategory.RADAR: "radar",
    RouteCategory.LEADERSHIP: "leadership",
    RouteCategory.NOISE: "noise",
}


class RouterDecision(BaseModel):
    category: RouteCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str | None = None


class Diagram(BaseModel):
    title: str
    diagram_type: str = Field(..., description='e.g. "mermaid", "ascii"')
    content: str


class TechnologyStory(BaseModel):
    """One article or major section inside a technology newsletter (e.g. multi-story digests)."""

    title: str = Field(..., max_length=500)
    article_url: str = Field(..., description="Must be copied verbatim from candidate article URLs in the prompt.")
    summary: str = Field(
        ...,
        max_length=1000,
        description="Up to ~1000 characters: substantive summary with concrete detail (not one sentence).",
    )


class TechnologyOutput(BaseModel):
    """Technology / systems newsletter extraction."""

    stories: list[TechnologyStory] = Field(default_factory=list)
    core_pain_point: str | None = Field(
        default=None,
        max_length=240,
        description="Legacy single-blurb mode; prefer ``stories`` when the email has one or more articles.",
    )
    diagrams: list[Diagram] = Field(default_factory=list)
    selected_image_urls: list[str] = Field(default_factory=list)
    digest_source_url: str | None = Field(
        default=None,
        description="Canonical / view-online URL from parsed HTML; set by the processor for digest fallback.",
    )

    @field_validator("selected_image_urls")
    @classmethod
    def _urls_subset_of_candidates(cls, v: list[str], info: ValidationInfo) -> list[str]:
        ctx = info.context
        if not ctx:
            return v
        allowed = ctx.get("allowed_image_urls")
        if allowed is None:
            return v
        allowed_set = set(allowed)
        bad = [u for u in v if u not in allowed_set]
        if bad:
            raise ValueError(
                "selected_image_urls must only contain URLs from the candidate list",
            )
        return v

    @field_validator("stories", mode="after")
    @classmethod
    def _story_urls_in_allowlist(cls, v: list[TechnologyStory], info: ValidationInfo) -> list[TechnologyStory]:
        ctx = info.context
        if not ctx or not v:
            return v
        allowed = ctx.get("allowed_article_urls")
        if allowed is None:
            return v
        allow = set(allowed)
        for s in v:
            if s.article_url not in allow:
                raise ValueError(
                    "story article_url must appear in the candidate article URL list from the user message",
                )
        return v

    @model_validator(mode="after")
    def _stories_or_legacy_blurb(self) -> TechnologyOutput:
        if self.stories:
            return self
        if self.core_pain_point and str(self.core_pain_point).strip():
            return self
        raise ValueError("Provide at least one story in ``stories``, or set legacy ``core_pain_point``.")


class RadarItem(BaseModel):
    entity: str
    impact_or_action: str
    url: str | None = None


class RadarOutput(BaseModel):
    items: list[RadarItem] = Field(default_factory=list)
    summary: str | None = None


class LeadershipSignal(BaseModel):
    theme: str
    insight: str
    actionable_item: str
    link: str | None = Field(
        default=None,
        description="URL when the signal refers to a course, product, or article (copy from email links).",
    )


class LeadershipOutput(BaseModel):
    signals: list[LeadershipSignal] = Field(default_factory=list)
    summary: str | None = None


class NoiseOutput(BaseModel):
    reason: str = Field(..., max_length=400)
    discard: bool = True

    @field_validator("reason")
    @classmethod
    def _single_sentence(cls, v: str) -> str:
        v = v.strip()
        if "\n" in v:
            raise ValueError("reason must be a single sentence (no newlines)")
        return v
