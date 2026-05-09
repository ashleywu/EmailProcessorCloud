from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RouteCategory(StrEnum):
    TECHNOLOGY = "TECHNOLOGY"
    RADAR = "RADAR"
    LEADERSHIP = "LEADERSHIP"
    NOISE = "NOISE"


class RouterDecision(BaseModel):
    route: RouteCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str | None = None


class Diagram(BaseModel):
    title: str
    diagram_type: str = Field(..., description='e.g. "mermaid", "ascii"')
    content: str


class TechnologyOutput(BaseModel):
    summary: str
    key_points: list[str] = Field(default_factory=list)
    diagram: Diagram | None = None


class RadarItem(BaseModel):
    title: str
    url: str | None = None
    note: str | None = None


class RadarOutput(BaseModel):
    items: list[RadarItem] = Field(default_factory=list)
    summary: str | None = None


class LeadershipSignal(BaseModel):
    theme: str
    insight: str


class LeadershipOutput(BaseModel):
    signals: list[LeadershipSignal] = Field(default_factory=list)
    summary: str | None = None


class NoiseOutput(BaseModel):
    reason: str
    discard: bool = True
