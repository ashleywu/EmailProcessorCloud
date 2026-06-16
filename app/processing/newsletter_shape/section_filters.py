"""Digest chrome / teaser section filters."""

from __future__ import annotations

from collections.abc import Sequence

from app.models.section import EmailSection
from app.processing.newsletter_shape.profile import NewsletterShapeProfile

_SHARED_DIGEST_EXCLUDED_PHRASES: tuple[str, ...] = (
    "become a paid subscriber",
    "unlock this piece",
    "get more out of your subscription",
    "what is included in a subscription",
    "what did you think of this post",
    "start free trial",
    "subscribe to read",
    "upgrade to paid",
    "sign up to read",
)


def is_digest_excluded_teaser_section(
    section: EmailSection,
    profile: NewsletterShapeProfile | None = None,
) -> bool:
    combined = " ".join(
        part for part in ((section.heading or ""), (section.text or "")) if part
    ).lower()
    if not combined.strip():
        return False

    phrases = _SHARED_DIGEST_EXCLUDED_PHRASES
    if profile is not None:
        phrases = phrases + profile.digest_excluded_phrases
    if any(phrase in combined for phrase in phrases):
        return True

    from app.parsing.content_unit_grouping import is_promo_section

    if is_promo_section(section) and len(section.text or "") < 600:
        return True
    return False


def filter_article_body_sections(
    sections: Sequence[EmailSection],
    profile: NewsletterShapeProfile | None = None,
) -> list[EmailSection]:
    from app.parsing.content_unit_grouping import is_promo_section

    return [
        section
        for section in sections
        if not is_promo_section(section)
        and not is_digest_excluded_teaser_section(section, profile)
    ]


def digest_excluded_section_keys(
    sections: Sequence[EmailSection],
    profile: NewsletterShapeProfile | None = None,
) -> list[str]:
    from app.parsing.content_unit_grouping import is_promo_section

    return [
        section.section_id.strip()
        for section in sections
        if is_digest_excluded_teaser_section(section, profile)
        or is_promo_section(section)
    ]
