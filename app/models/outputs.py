from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class RouteCategory(StrEnum):
    TECHNOLOGY = "TECHNOLOGY"
    RADAR = "RADAR"
    LEADERSHIP = "LEADERSHIP"
    NOISE = "NOISE"


class RouterDecision(BaseModel):
    category: RouteCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str | None = None


class Diagram(BaseModel):
    title: str
    diagram_type: str = Field(..., description='e.g. "mermaid", "ascii"')
    content: str


class TechnologyOutput(BaseModel):
    core_pain_point: str = Field(..., max_length=240)
    diagrams: list[Diagram] = Field(default_factory=list)
    selected_image_urls: list[str] = Field(default_factory=list)

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
