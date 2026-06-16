from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.outputs import RouteCategory


class ClassificationRoutingSource(StrEnum):
    SENDER_PRIOR = "sender_prior"
    SENDER_PROFILE = "sender_profile"
    SENDER_OVERRIDE = "sender_override"
    HEURISTIC = "heuristic"
    LLM_CLASSIFIER = "llm_classifier"


class ConfidenceBandAction(StrEnum):
    PROCESS = "process"
    WARN = "warn"
    FAIL = "fail"


class ContentUnit(BaseModel):
    content_unit_key: str = Field(..., min_length=1)
    unit_text: str = ""
    headings: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    section_keys: list[str] = Field(default_factory=list)


class ContentUnitClassifierLLMOutput(BaseModel):
    category: RouteCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    primary_value: str
    evidence: list[str] = Field(default_factory=list)


class ContentUnitClassificationResult(BaseModel):
    category: RouteCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    primary_value: str = ""
    evidence: list[str] = Field(default_factory=list)
    routing_source: ClassificationRoutingSource
    warnings: list[str] = Field(default_factory=list)
    # Profile fast-path audit fields (``routing_source=sender_profile`` only).
    sender_profile: str | None = None
    grouping_strategy: str | None = None
    content_hash: str | None = None
    processor_kind: str | None = None


class ConfidenceBandResult(BaseModel):
    action: ConfidenceBandAction
    result: ContentUnitClassificationResult


# ---------------------------------------------------------------------------
# Phase 7 — boundary classifier models
# ---------------------------------------------------------------------------


class GroupingAmbiguityReason(StrEnum):
    MIXED_HEADING_PATTERN = "mixed_heading_pattern"
    AMBIGUOUS_URL_COUNT = "ambiguous_url_count"
    SECTION_COUNT_GRAY_ZONE = "section_count_gray_zone"
    NO_NUMBERED_CHAPTER_SIGNAL = "no_numbered_chapter_signal"
    MIXED_CHAR_DISTRIBUTION = "mixed_char_distribution"


class GroupingResult(BaseModel):
    """Return value of ``group_content_units()`` (Phase 7+)."""

    units: list[ContentUnit]
    conservative_units: list[ContentUnit]
    ambiguous: bool
    ambiguity_reasons: list[GroupingAmbiguityReason] = Field(default_factory=list)
    non_promo_section_count: int = 0
    digest_shape: str | None = None
    digest_excluded_section_keys: list[str] = Field(default_factory=list)
    shape_profile_id: str | None = None
    distinct_canonical_story_urls: list[str] = Field(default_factory=list)
    substantive_article_chars: int = 0
    merged_section_keys: list[str] = Field(default_factory=list)


class BoundaryOutlineSection(BaseModel):
    """Structural outline entry sent to the boundary classifier — no full content."""

    section_key: str
    heading: str | None = None
    snippet: str = ""
    char_count: int = 0
    link_count: int = 0
    primary_links: list[str] = Field(default_factory=list)


class BoundaryUnitType(StrEnum):
    LONG_FORM = "long_form"
    INTERVIEW_TRANSCRIPT = "interview_transcript"
    LINK_ROUNDUP = "link_roundup"
    PROMO = "promo"
    STANDALONE = "standalone"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class BoundaryLLMUnit(BaseModel):
    unit_title: str
    section_keys: list[str]
    unit_type: BoundaryUnitType
    reason: str


class BoundaryLLMOutput(BaseModel):
    units: list[BoundaryLLMUnit]
    confidence: float = Field(..., ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class BoundaryBudgetStatus(StrEnum):
    OK = "ok"
    SECTION_COUNT_EXCEEDED = "section_count_exceeded"
    SNIPPET_TRUNCATED = "snippet_truncated"
    PROMPT_SIZE_EXCEEDED = "prompt_size_exceeded"
    LLM_SKIPPED_DISABLED = "llm_skipped_disabled"


class BoundaryClassificationResult(BaseModel):
    """Persisted as ``agent_outputs`` kind=``boundary_classifier``."""

    outline_hash: str
    deterministic_units: list[ContentUnit]
    llm_units: list[BoundaryLLMUnit] | None = None
    accepted_units: list[ContentUnit]
    fallback_used: bool
    fallback_reason: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    confidence: float | None = None
    ambiguity_reasons: list[GroupingAmbiguityReason] = Field(default_factory=list)
    budget_status: BoundaryBudgetStatus = BoundaryBudgetStatus.OK
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "BoundaryBudgetStatus",
    "BoundaryClassificationResult",
    "BoundaryLLMOutput",
    "BoundaryLLMUnit",
    "BoundaryOutlineSection",
    "BoundaryUnitType",
    "ClassificationRoutingSource",
    "ConfidenceBandAction",
    "ConfidenceBandResult",
    "ContentUnit",
    "ContentUnitClassificationResult",
    "ContentUnitClassifierLLMOutput",
    "GroupingAmbiguityReason",
    "GroupingResult",
]
