"""Newsletter shape profile types."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field


class DigestEmailShape(StrEnum):
    SINGLE_ARTICLE = "single_article"
    MULTI_STORY = "multi_story"
    TEASER_PAYWALL = "teaser_paywall"


@dataclass(frozen=True, slots=True)
class TrackingUnwrapRule:
    """Decode click-tracking host to embedded destination URL."""

    tracking_hosts: frozenset[str]
    path_markers: tuple[str, ...] = ("/cl0/", "/cl1/")


@dataclass(frozen=True, slots=True)
class PrimaryUrlRules:
    article_hosts: frozenset[str]
    story_path_patterns: tuple[re.Pattern[str], ...]
    non_article_path_prefixes: tuple[str, ...]
    tracking_unwrap: tuple[TrackingUnwrapRule, ...] = ()
    beehiiv_query_keys: tuple[str, ...] = ("url", "redirect", "u")
    strip_query_prefixes: tuple[str, ...] = ("utm_",)
    strip_query_names: frozenset[str] = frozenset({"_bhlid", "ref"})


@dataclass(frozen=True, slots=True)
class NewsletterShapeProfile:
    profile_id: str
    sender_emails: frozenset[str]
    sender_domains: frozenset[str]
    primary_url: PrimaryUrlRules
    digest_excluded_phrases: tuple[str, ...] = ()
    min_substantive_article_chars: int = 400
    multi_story_primary_threshold: int = 2
    allow_original_url_lookup: bool = False


class NewsletterShapeDecision(BaseModel):
    """Persisted as ``agent_outputs`` kind=``shape_classifier``."""

    shape_profile_id: str
    digest_shape: str
    digest_excluded_section_keys: list[str] = Field(default_factory=list)
    distinct_canonical_story_urls: list[str] = Field(default_factory=list)
    substantive_article_chars: int = 0
    merged_section_keys: list[str] = Field(default_factory=list)
    routing_source: str = "newsletter_shape_profile"
