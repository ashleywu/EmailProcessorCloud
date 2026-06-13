from __future__ import annotations

from typing import Any

from app.models.content_units import (
    ClassificationRoutingSource,
    ContentUnit,
    ContentUnitClassificationResult,
)
from app.models.outputs import RouteCategory
from app.processing.confidence_band import CONFIDENCE_HEURISTIC_STRONG, CONFIDENCE_SENDER_PRIOR

_PROMO_KEYWORDS = (
    "register",
    "enroll",
    "cohort",
    "webinar",
    "workshop",
    "masterclass",
    "bootcamp",
    "rsvp",
    "limited seats",
    "apply now",
    "tickets",
    "early bird",
    "join us",
    "sign up",
)


def classify_content_unit(
    unit: ContentUnit,
    outline: Any,
    prior: Any,
    sanity: Any,
    classifier_agent: Any,
    parsed: Any,
) -> ContentUnitClassificationResult:
    category_from_prior = _resolve_prior_category(prior)
    if category_from_prior is not None and _sanity_is_trust(sanity):
        return ContentUnitClassificationResult(
            category=category_from_prior,
            confidence=CONFIDENCE_SENDER_PRIOR,
            rationale="Sender prior accepted after trust-tier sanity check.",
            primary_value=f"Prior-routed as {category_from_prior.value}.",
            evidence=_unit_evidence(unit),
            routing_source=ClassificationRoutingSource.SENDER_PRIOR,
        )

    promo_hit_count = _promo_signal_count(unit)
    if promo_hit_count >= 2:
        return ContentUnitClassificationResult(
            category=RouteCategory.COURSES,
            confidence=CONFIDENCE_HEURISTIC_STRONG,
            rationale="Strong promotional lexical signal detected in the content unit.",
            primary_value="Enrollment/promo-oriented call to action.",
            evidence=_unit_evidence(unit),
            routing_source=ClassificationRoutingSource.HEURISTIC,
        )

    return classifier_agent.classify(
        unit=unit,
        subject=_extract_subject(parsed),
        outline=outline,
        prior=prior,
        sanity=sanity,
        parsed=parsed,
    )


def _resolve_prior_category(prior: Any) -> RouteCategory | None:
    candidates: list[Any] = []
    if isinstance(prior, dict):
        candidates.append(prior.get("category"))
        candidates.append(prior.get("route_category"))
        candidates.append(prior.get("default_category"))
    else:
        for attr in ("category", "route_category", "default_category"):
            candidates.append(getattr(prior, attr, None))

    for value in candidates:
        if value is None:
            continue
        if isinstance(value, RouteCategory):
            return value
        raw = str(value).strip()
        if not raw:
            continue
        try:
            return RouteCategory(raw)
        except ValueError:
            continue
    return None


def _sanity_is_trust(sanity: Any) -> bool:
    if sanity is None:
        return False
    if isinstance(sanity, dict):
        tier = str(sanity.get("tier", "")).strip().lower()
        return tier == "trust" or bool(sanity.get("is_trust"))
    tier_raw = str(getattr(sanity, "tier", "")).strip().lower()
    if tier_raw == "trust":
        return True
    return bool(getattr(sanity, "is_trust", False))


def _promo_signal_count(unit: ContentUnit) -> int:
    text = " ".join([*unit.headings, unit.unit_text]).lower()
    return sum(1 for kw in _PROMO_KEYWORDS if kw in text)


def _extract_subject(parsed: Any) -> str | None:
    if parsed is None:
        return None
    subject = getattr(parsed, "subject", None)
    if subject is None and isinstance(parsed, dict):
        subject = parsed.get("subject")
    if subject is None:
        return None
    s = str(subject).strip()
    return s or None


def _unit_evidence(unit: ContentUnit) -> list[str]:
    evidence: list[str] = []
    if unit.headings:
        evidence.append(f"Headings: {', '.join(unit.headings[:3])}")
    snippet = " ".join(unit.unit_text.split())[:240]
    if snippet:
        evidence.append(f"Text snippet: {snippet}")
    return evidence
