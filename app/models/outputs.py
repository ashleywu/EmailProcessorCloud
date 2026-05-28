from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


class RouteCategory(StrEnum):
    TECHNOLOGY = "TECHNOLOGY"
    RADAR = "RADAR"
    LEADERSHIP = "LEADERSHIP"
    COURSES = "COURSES"


# Persisted ``agent_outputs.kind`` for each router category (single source of truth).
PROCESSOR_OUTPUT_KIND: dict[RouteCategory, str] = {
    RouteCategory.TECHNOLOGY: "technology",
    RouteCategory.RADAR: "radar",
    RouteCategory.LEADERSHIP: "leadership",
    RouteCategory.COURSES: "courses",
}


class RouterDecision(BaseModel):
    category: RouteCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str | None = None

    @field_validator("category", mode="before")
    @classmethod
    def _coerce_legacy_category_strings(cls, v: object) -> object:
        if v in ("EVERY_BUNDLE", "MULTI_BUNDLE"):
            return "TECHNOLOGY"
        if v == "NOISE":
            return "COURSES"
        return v


class RouterLLMCategory(StrEnum):
    """Subset allowed from the hosted router model."""

    TECHNOLOGY = "TECHNOLOGY"
    RADAR = "RADAR"
    LEADERSHIP = "LEADERSHIP"
    COURSES = "COURSES"


class RouterLLMDecision(BaseModel):
    category: RouterLLMCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str | None = None

    def to_router_decision(self) -> RouterDecision:
        return RouterDecision(
            category=RouteCategory(self.category.value),
            confidence=self.confidence,
            rationale=self.rationale,
        )


class Diagram(BaseModel):
    title: str
    diagram_type: str = Field(..., description='e.g. "mermaid", "ascii"')
    content: str


class TechnologySectionOutput(BaseModel):
    """Single Technical Index slice (section router + section processor).

    Uses **section-local** payloads only — no bundled radar / leadership / courses fields.
    """

    title: str = Field(..., max_length=500)
    core_pain_point: str = Field(..., max_length=240)
    original_url: str = Field(..., description="Primary article URL copied from candidate list.")
    diagrams: list[Diagram] = Field(default_factory=list)

    @field_validator("original_url")
    @classmethod
    def _https_original(cls, v: str) -> str:
        s = str(v).strip()
        if not s.startswith("https://"):
            raise ValueError("original_url must start with https://")
        return s

    @model_validator(mode="after")
    def _original_url_allowlisted(self, info: ValidationInfo) -> TechnologySectionOutput:
        ctx = info.context or {}
        allow = ctx.get("allowed_article_urls")
        if allow is None:
            return self
        if self.original_url not in set(allow):
            raise ValueError("original_url must appear in candidate article URLs from this section")
        return self


class LeadershipSectionOutput(BaseModel):
    """Leadership Signals slice for exactly one routed section."""

    signals: list[LeadershipSignal] = Field(default_factory=list)
    summary: str | None = None

    @model_validator(mode="after")
    def _non_empty(self) -> LeadershipSectionOutput:
        if self.signals or (self.summary and str(self.summary).strip()):
            return self
        raise ValueError(
            "Provide non-empty signals and/or summary for this leadership slice.",
        )

    @model_validator(mode="after")
    def _signal_links_allowlisted(self, info: ValidationInfo) -> LeadershipSectionOutput:
        ctx = info.context or {}
        allow = ctx.get("allowed_action_urls")
        if allow is None:
            return self
        allow_set = set(allow)
        for sig in self.signals:
            if sig.link is not None and str(sig.link).strip():
                lk = str(sig.link).strip()
                if lk not in allow_set:
                    raise ValueError("LeadershipSignal.link must be listed in HTTPS candidates")
        return self


class TechnologyStory(BaseModel):
    """One article or major section inside a technology newsletter (e.g. multi-story digests)."""

    title: str = Field(..., max_length=500)
    article_url: str = Field(..., description="Must be copied verbatim from candidate article URLs in the prompt.")
    summary: str = Field(
        ...,
        max_length=1000,
        description="Up to ~1000 characters: substantive summary with concrete detail (not one sentence).",
    )


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


class LeadershipColumnOutput(BaseModel):
    """Essay-only block embedded in ``TechnologyOutput`` (no roundup/session slots here)."""

    signals: list[LeadershipSignal] = Field(default_factory=list)
    summary: str | None = None

    @model_validator(mode="after")
    def _column_nonempty(self) -> LeadershipColumnOutput:
        if self.signals or (self.summary and str(self.summary).strip()):
            return self
        raise ValueError(
            "``leadership_excerpt`` must include ``signals`` and/or ``summary`` when present.",
        )


class LeadershipOutput(BaseModel):
    """Primary leadership column; optional same-email roundup + session promos."""

    signals: list[LeadershipSignal] = Field(default_factory=list)
    summary: str | None = None
    roundup_radar: RadarOutput | None = None
    session_promos: CoursesOutput | None = Field(
        default=None,
        description="RSVP / cohort / webinar blocks in the same mailing (fill when router is LEADERSHIP).",
    )

    @model_validator(mode="after")
    def _has_some_content(self) -> LeadershipOutput:
        has_col = bool(self.signals) or (self.summary and str(self.summary).strip())
        r = self.roundup_radar
        has_radar = bool(r and (r.items or (r.summary and str(r.summary).strip())))
        c = self.session_promos
        has_courses = bool(
            c and (str(c.summary).strip() or c.actions or c.promo_blocks),
        )
        if has_col or has_radar or has_courses:
            return self
        raise ValueError(
            "Provide leadership ``signals``/``summary`` and/or ``roundup_radar`` and/or ``session_promos``.",
        )


class CourseActionItem(BaseModel):
    label: str = Field(..., max_length=200)
    url: str = Field(..., description="HTTPS URL copied from the newsletter candidate list.")

    @field_validator("url")
    @classmethod
    def _https_only(cls, v: str) -> str:
        s = str(v).strip()
        if not s.startswith("https://"):
            raise ValueError("course action url must be https")
        return s


class CoursePromoBlock(BaseModel):
    """One distinct event/session with its own blurb and primary CTA (multi-RSVP mailings)."""

    text: str = Field(..., max_length=2000, description="Factual recap for this event only.")
    cta: CourseActionItem = Field(
        ...,
        description="HTTPS link belonging to this block (candidate list only).",
    )


class CoursesOutput(BaseModel):
    """Structured summary for course / webinar / RSVP heavy newsletters (router COURSES)."""

    summary: str = Field("", max_length=4000)
    actions: list[CourseActionItem] = Field(default_factory=list)
    promo_blocks: list[CoursePromoBlock] = Field(
        default_factory=list,
        description="When mailings advertise multiple distinct RSVP/session blocks, pair each recap with its CTA.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_noise(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "summary" in data or "actions" in data:
            return data
        if "reason" in data:
            reason = str(data.get("reason") or "").strip()
            flat = " ".join(reason.split())
            return {
                "summary": flat or "Legacy noise entry (no summary).",
                "actions": [],
            }
        return data

    @model_validator(mode="after")
    def _nonempty_cards(self) -> CoursesOutput:
        if (
            str(self.summary).strip()
            or self.actions
            or self.promo_blocks
        ):
            return self
        raise ValueError(
            "Provide non-empty summary and/or actions and/or promo_blocks.",
        )

    @model_validator(mode="after")
    def _action_urls_allowlisted(self, info: ValidationInfo) -> CoursesOutput:
        ctx = info.context or {}
        allowed_raw = ctx.get("allowed_action_urls")
        if allowed_raw is None:
            return self
        allow = set(allowed_raw)
        for a in self.actions:
            if a.url not in allow:
                raise ValueError(
                    "course action url must appear in the candidate link list from the user message",
                )
        for b in self.promo_blocks:
            if b.cta.url not in allow:
                raise ValueError(
                    "course promo_blocks cta url must appear in the candidate link list from the user message",
                )
        return self


class TechnologyOutput(BaseModel):
    """Technology extraction; may also carry leadership column + roundup + sessions from same email."""

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
    leadership_excerpt: LeadershipColumnOutput | None = Field(
        default=None,
        description="Essay column in the same issue (signals + summary only); roundups → ``roundup_radar``.",
    )
    roundup_radar: RadarOutput | None = None
    session_promos: CoursesOutput | None = Field(
        default=None,
        description="Courses / webinars / RSVP blocks in the same mailing.",
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
    def _nonempty_output(self) -> TechnologyOutput:
        has_stories = bool(self.stories)
        has_blurb = bool(self.core_pain_point and str(self.core_pain_point).strip())
        le = self.leadership_excerpt
        has_lead = False
        if le is not None:
            has_lead = bool(le.signals) or (le.summary and str(le.summary).strip())
        r = self.roundup_radar
        has_radar = bool(r and (r.items or (r.summary and str(r.summary).strip())))
        sp = self.session_promos
        has_sessions = bool(
            sp and (str(sp.summary).strip() or sp.actions or sp.promo_blocks),
        )
        if has_stories or has_blurb or has_lead or has_radar or has_sessions:
            return self
        raise ValueError(
            "Provide ``stories`` or ``core_pain_point`` or ``leadership_excerpt`` "
            "or ``roundup_radar`` or ``session_promos``.",
        )
