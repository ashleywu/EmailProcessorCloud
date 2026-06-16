"""Three-shape classifier with V1 strong-evidence multi-story."""

from __future__ import annotations

from collections.abc import Sequence

from app.models.section import EmailSection
from app.processing.newsletter_shape.grouping import (
    build_multi_story_units,
    build_single_article_unit,
    substantive_article_chars,
)
from app.processing.newsletter_shape.primary_urls import (
    _canonical_from_original,
    collect_distinct_canonical_story_urls,
    dominant_section_story_path,
)
from app.processing.newsletter_shape.profile import DigestEmailShape, NewsletterShapeProfile
from app.processing.newsletter_shape.section_filters import filter_article_body_sections


def _strong_multi_story(
    sections: Sequence[EmailSection],
    profile: NewsletterShapeProfile,
    *,
    original_url: str | None,
    distinct_urls: set[str],
) -> bool:
    if len(distinct_urls) < profile.multi_story_primary_threshold:
        return False

    canonical = _canonical_from_original(original_url, profile)
    blocks: dict[str, list[EmailSection]] = {url: [] for url in distinct_urls}
    for section in filter_article_body_sections(sections, profile):
        dominant = dominant_section_story_path(section, profile, canonical=canonical)
        if dominant is not None and dominant in blocks:
            blocks[dominant].append(section)

    for url in distinct_urls:
        block = blocks.get(url, [])
        chars = sum(len(section.text or "") for section in block)
        if not block or chars < profile.min_substantive_article_chars:
            return False
    return True


def classify_newsletter_shape(
    sections: Sequence[EmailSection],
    *,
    original_url: str | None,
    profile: NewsletterShapeProfile,
) -> DigestEmailShape:
    article_chars = substantive_article_chars(sections, profile)
    if article_chars < profile.min_substantive_article_chars:
        return DigestEmailShape.TEASER_PAYWALL

    distinct = collect_distinct_canonical_story_urls(
        sections,
        original_url=original_url,
        profile=profile,
    )
    if _strong_multi_story(
        sections,
        profile,
        original_url=original_url,
        distinct_urls=distinct,
    ):
        return DigestEmailShape.MULTI_STORY
    return DigestEmailShape.SINGLE_ARTICLE


def build_shape_units(
    sections: Sequence[EmailSection],
    *,
    original_url: str | None,
    profile: NewsletterShapeProfile,
    shape: DigestEmailShape,
) -> list:
    if shape == DigestEmailShape.TEASER_PAYWALL:
        return []
    if shape == DigestEmailShape.SINGLE_ARTICLE:
        return build_single_article_unit(sections, profile)
    distinct = collect_distinct_canonical_story_urls(
        sections,
        original_url=original_url,
        profile=profile,
    )
    return build_multi_story_units(
        sections,
        profile,
        story_urls=distinct,
        original_url=original_url,
    )
