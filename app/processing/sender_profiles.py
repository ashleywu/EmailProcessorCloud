"""Sender profile registry (V1 SP0/SP1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.models.outputs import RouteCategory
from app.parsing.sender_match import normalize_sender_email

ARTICLE_BODY_MIN_CHARS = 200
PROMO_DOMINATED_RATIO = 0.5


class GroupingStrategy(StrEnum):
    AINEWS_MAP_REDUCE = "ainews_map_reduce"
    SINGLE_TECH_ARTICLE = "single_tech_article"
    SINGLE_LEADERSHIP_ESSAY = "single_leadership_essay"
    SINGLE_TECH_LONGFORM = "single_tech_longform"
    TECH_ARTICLE_OPTIONAL_RADAR = "tech_article_optional_radar"


@dataclass(frozen=True, slots=True)
class SenderProfile:
    sender_email: str
    strategy: GroupingStrategy
    default_category: RouteCategory
    processor: str
    fallback_strategy: str = "generic_content_unit"
    promo_handling: str = "strip_strippable_and_hide"
    maximum_digest_cards: dict[str, int] = field(default_factory=dict)
    counter_evidence_rules: tuple[str, ...] = ("promo_dominated", "empty_body")
    skip_boundary_classifier: bool = True
    skip_content_unit_classifier: bool = True


SENDER_PROFILES: dict[str, SenderProfile] = {
    "bytebytego@substack.com": SenderProfile(
        sender_email="bytebytego@substack.com",
        strategy=GroupingStrategy.SINGLE_TECH_ARTICLE,
        default_category=RouteCategory.TECHNOLOGY,
        processor="technology",
        maximum_digest_cards={"technology": 1},
        counter_evidence_rules=("promo_dominated", "empty_body"),
    ),
    "alifeengineered@substack.com": SenderProfile(
        sender_email="alifeengineered@substack.com",
        strategy=GroupingStrategy.SINGLE_LEADERSHIP_ESSAY,
        default_category=RouteCategory.LEADERSHIP,
        processor="leadership_essay",
        maximum_digest_cards={"leadership": 1},
        counter_evidence_rules=("promo_dominated", "empty_body"),
    ),
    "swyx@substack.com": SenderProfile(
        sender_email="swyx@substack.com",
        strategy=GroupingStrategy.SINGLE_TECH_LONGFORM,
        default_category=RouteCategory.TECHNOLOGY,
        processor="technical_longform",
        maximum_digest_cards={"technology": 1},
        counter_evidence_rules=("promo_dominated", "empty_body"),
    ),
}


def lookup_sender_profile(from_header: str | None) -> SenderProfile | None:
    email = normalize_sender_email(from_header)
    if email is None:
        return None
    return SENDER_PROFILES.get(email)


__all__ = [
    "ARTICLE_BODY_MIN_CHARS",
    "GroupingStrategy",
    "PROMO_DOMINATED_RATIO",
    "SENDER_PROFILES",
    "SenderProfile",
    "lookup_sender_profile",
]
