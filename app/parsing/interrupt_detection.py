"""P1a — deterministic per-section interrupt role detection (publication-agnostic)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.models.section import EmailSection
from app.parsing.rules import (
    SPONSOR_CLASS_SUBSTRINGS,
    UNSUBSCRIBE_FOOTER_PHRASES,
    VIEW_IN_BROWSER_PHRASES,
)

_COPYRIGHT_RE = re.compile(r"©\s*20\d{2}")

_PROMO_KEYWORDS: tuple[str, ...] = (
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
    "sponsor",
)

_STRONG_PROMO_HEADING_MARKERS: tuple[str, ...] = (
    "(sponsored)",
    "sponsor:",
    "paid partnership",
    "advertisement",
    "promoted by",
)

_NAVIGATION_PHRASES: tuple[str, ...] = tuple(VIEW_IN_BROWSER_PHRASES) + (
    "read in app",
    "share this",
    "read this email",
)

_SUBSCRIPTION_CTA_PHRASES: tuple[str, ...] = (
    "become a paid subscriber",
    "upgrade your subscription",
    "upgrade to paid",
    "subscribe to read",
    "sign up to read",
)

_SHORT_SECTION_CHAR_LIMIT = 200


class InterruptRole(StrEnum):
    NORMAL_CONTENT = "normal_content"
    PROMO = "promo"
    NAVIGATION = "navigation"
    SUBSCRIPTION_CTA = "subscription_cta"
    FOOTER = "footer"
    UNKNOWN_INTERRUPT = "unknown_interrupt"


STRIPPABLE_INTERRUPT_ROLES = frozenset(
    {
        InterruptRole.PROMO,
        InterruptRole.NAVIGATION,
        InterruptRole.FOOTER,
        InterruptRole.SUBSCRIPTION_CTA,
    },
)


def is_strippable_interrupt(role: InterruptRole) -> bool:
    return role in STRIPPABLE_INTERRUPT_ROLES


def is_article_body_section(role: InterruptRole) -> bool:
    return role in {InterruptRole.NORMAL_CONTENT, InterruptRole.UNKNOWN_INTERRUPT}


def _combined_text(section: EmailSection) -> str:
    parts = [section.heading or "", section.text or ""]
    return " ".join(part.strip() for part in parts if part and part.strip()).lower()


def _heading_text(section: EmailSection) -> str:
    return (section.heading or "").strip().lower()


def _promo_keyword_hits(text: str) -> int:
    return sum(1 for kw in _PROMO_KEYWORDS if kw in text)


def _matches_any(text: str, phrases: Sequence[str]) -> bool:
    return any(phrase in text for phrase in phrases)


@dataclass(frozen=True, slots=True)
class InterruptRoleDecision:
    role: InterruptRole
    rule: str


def _footer_rule(
    section: EmailSection,
    *,
    section_index: int,
    total_sections: int,
) -> str | None:
    text = _combined_text(section)
    if _matches_any(text, UNSUBSCRIBE_FOOTER_PHRASES):
        return "footer:unsubscribe_phrase"
    if _COPYRIGHT_RE.search(text):
        return "footer:copyright"
    if total_sections > 0 and section_index >= int(total_sections * 0.9):
        https_links = [str(link).strip() for link in section.links if str(link).startswith("https://")]
        if len(section.text or "") < 400 and len(https_links) >= 2:
            return "footer:bottom_tenth_link_heavy"
    return None


def _navigation_rule(section: EmailSection) -> str | None:
    text = _combined_text(section)
    if not _matches_any(text, _NAVIGATION_PHRASES):
        return None
    if len(section.text or "") >= _SHORT_SECTION_CHAR_LIMIT:
        return None
    https_links = [str(link).strip() for link in section.links if str(link).startswith("https://")]
    if len(https_links) >= 1 or len(section.text or "") < 120:
        return "navigation:phrase_match"
    return None


def _subscription_cta_rule(section: EmailSection) -> str | None:
    text = _combined_text(section)
    if not _matches_any(text, _SUBSCRIPTION_CTA_PHRASES + ("subscribe", "sign up")):
        return None
    if len(section.text or "") > 600:
        return None
    if any("substack.com" in str(link) for link in section.links) or len(section.text or "") < 350:
        return "subscription_cta:phrase_match"
    return None


def _strong_promo_rule(section: EmailSection) -> str | None:
    heading = _heading_text(section)
    text = _combined_text(section)
    for marker in _STRONG_PROMO_HEADING_MARKERS:
        if marker in heading:
            return "promo:strong_heading_marker"
    for marker in ("(sponsored)", "paid partnership", "promoted by"):
        if marker in text:
            return "promo:body_marker"
    for marker in SPONSOR_CLASS_SUBSTRINGS:
        if marker in heading:
            return "promo:sponsor_class_substring"
    return None


def _unknown_interrupt_rule(section: EmailSection) -> str | None:
    text = _combined_text(section)
    hits = _promo_keyword_hits(text)
    if hits == 1:
        return "unknown_interrupt:single_promo_keyword"
    if hits >= 2 and _strong_promo_rule(section) is None:
        return "unknown_interrupt:multi_promo_keyword"
    if len(section.text or "") < 120:
        https_links = [str(link).strip() for link in section.links if str(link).startswith("https://")]
        if len(https_links) >= 2 and len(section.text or "") < 80:
            return "unknown_interrupt:short_link_heavy"
    return None


def _is_footer(section: EmailSection, *, section_index: int, total_sections: int) -> bool:
    return _footer_rule(section, section_index=section_index, total_sections=total_sections) is not None


def _is_navigation(section: EmailSection) -> bool:
    return _navigation_rule(section) is not None


def _is_subscription_cta(section: EmailSection) -> bool:
    return _subscription_cta_rule(section) is not None


def _is_strong_promo(section: EmailSection) -> bool:
    return _strong_promo_rule(section) is not None


def _is_unknown_interrupt(section: EmailSection) -> bool:
    return _unknown_interrupt_rule(section) is not None


def explain_interrupt_role(
    section: EmailSection,
    *,
    section_index: int = 0,
    total_sections: int = 1,
) -> InterruptRoleDecision:
    """Assign exactly one interrupt role and the first matching detection rule."""

    footer = _footer_rule(section, section_index=section_index, total_sections=total_sections)
    if footer is not None:
        return InterruptRoleDecision(role=InterruptRole.FOOTER, rule=footer)

    navigation = _navigation_rule(section)
    if navigation is not None:
        return InterruptRoleDecision(role=InterruptRole.NAVIGATION, rule=navigation)

    subscription = _subscription_cta_rule(section)
    if subscription is not None:
        return InterruptRoleDecision(role=InterruptRole.SUBSCRIPTION_CTA, rule=subscription)

    promo = _strong_promo_rule(section)
    if promo is not None:
        return InterruptRoleDecision(role=InterruptRole.PROMO, rule=promo)

    unknown = _unknown_interrupt_rule(section)
    if unknown is not None:
        return InterruptRoleDecision(role=InterruptRole.UNKNOWN_INTERRUPT, rule=unknown)

    return InterruptRoleDecision(role=InterruptRole.NORMAL_CONTENT, rule="normal_content:default")


def detect_interrupt_role(
    section: EmailSection,
    *,
    section_index: int = 0,
    total_sections: int = 1,
) -> InterruptRole:
    """Assign exactly one interrupt role using precision-first priority order."""

    return explain_interrupt_role(
        section,
        section_index=section_index,
        total_sections=total_sections,
    ).role


def detect_interrupt_roles(sections: Sequence[EmailSection]) -> list[InterruptRole]:
    total = len(sections)
    return [
        detect_interrupt_role(section, section_index=index, total_sections=total)
        for index, section in enumerate(sections)
    ]


def explain_interrupt_roles(sections: Sequence[EmailSection]) -> list[InterruptRoleDecision]:
    total = len(sections)
    return [
        explain_interrupt_role(section, section_index=index, total_sections=total)
        for index, section in enumerate(sections)
    ]


__all__ = [
    "InterruptRole",
    "InterruptRoleDecision",
    "STRIPPABLE_INTERRUPT_ROLES",
    "detect_interrupt_role",
    "detect_interrupt_roles",
    "explain_interrupt_role",
    "explain_interrupt_roles",
    "is_article_body_section",
    "is_strippable_interrupt",
]
