"""Shape grouping: single merge and strong-evidence multi-story split."""

from __future__ import annotations

from collections.abc import Sequence

from app.models.content_units import ContentUnit
from app.models.section import EmailSection
from app.parsing.content_unit_grouping import build_content_units_from_section_groups
from app.processing.newsletter_shape.primary_urls import (
    _canonical_from_original,
    dominant_section_story_path,
)
from app.processing.newsletter_shape.profile import NewsletterShapeProfile
from app.processing.newsletter_shape.section_filters import filter_article_body_sections


def build_single_article_unit(
    sections: Sequence[EmailSection],
    profile: NewsletterShapeProfile,
) -> list[ContentUnit]:
    article_sections = filter_article_body_sections(sections, profile)
    if not article_sections:
        return []
    return build_content_units_from_section_groups([article_sections])


def build_multi_story_units(
    sections: Sequence[EmailSection],
    profile: NewsletterShapeProfile,
    *,
    story_urls: set[str],
    original_url: str | None,
) -> list[ContentUnit]:
    canonical = _canonical_from_original(original_url, profile)
    article_sections = filter_article_body_sections(sections, profile)
    groups: dict[str, list[EmailSection]] = {url: [] for url in sorted(story_urls)}

    for section in article_sections:
        dominant = dominant_section_story_path(section, profile, canonical=canonical)
        if dominant is None or dominant not in groups:
            continue
        groups[dominant].append(section)

    ordered_groups = [groups[url] for url in sorted(story_urls) if groups[url]]
    return build_content_units_from_section_groups(ordered_groups)


def substantive_article_chars(
    sections: Sequence[EmailSection],
    profile: NewsletterShapeProfile,
) -> int:
    return sum(len(section.text or "") for section in filter_article_body_sections(sections, profile))
