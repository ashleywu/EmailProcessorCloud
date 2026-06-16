"""Registry: Every.to and Turing Post shape profiles."""

from __future__ import annotations

import re

from app.parsing.sender_match import normalize_sender_email
from app.processing.newsletter_shape.primary_urls import is_story_original_url
from app.processing.newsletter_shape.profile import (
    NewsletterShapeProfile,
    PrimaryUrlRules,
    TrackingUnwrapRule,
)

_EVERY_STORY_PATTERNS = (
    re.compile(r"^/p/[^/]+$"),
    re.compile(r"^/[^/]+/[^/]+$"),
)

_TURING_STORY_PATTERNS = (re.compile(r"^/p/[^/]+$"),)

EVERY_TO_PROFILE = NewsletterShapeProfile(
    profile_id="every_to",
    sender_emails=frozenset({"hello@every.to", "every@every.to"}),
    sender_domains=frozenset({"every.to"}),
    allow_original_url_lookup=True,
    primary_url=PrimaryUrlRules(
        article_hosts=frozenset({"every.to", "www.every.to"}),
        story_path_patterns=_EVERY_STORY_PATTERNS,
        non_article_path_prefixes=(
            "/subscribe",
            "/account",
            "/products",
            "/consulting",
            "/studio",
            "/emails/",
            "/newsletter",
        ),
        tracking_unwrap=(
            TrackingUnwrapRule(tracking_hosts=frozenset({"icu.every.to"})),
        ),
    ),
)

TURING_POST_PROFILE = NewsletterShapeProfile(
    profile_id="turing_post",
    sender_emails=frozenset({"turingpost@mail.beehiiv.com"}),
    sender_domains=frozenset(),
    allow_original_url_lookup=False,
    primary_url=PrimaryUrlRules(
        article_hosts=frozenset({"turingpost.com", "www.turingpost.com"}),
        story_path_patterns=_TURING_STORY_PATTERNS,
        non_article_path_prefixes=(
            "/subscribe",
            "/login",
            "/share",
            "/comments",
            "/archive",
        ),
        tracking_unwrap=(
            TrackingUnwrapRule(
                tracking_hosts=frozenset(
                    {
                        "link.mail.beehiiv.com",
                        "clicks.beehiiv.com",
                        "mail.beehiiv.com",
                    },
                ),
                path_markers=(),
            ),
        ),
    ),
)

NEWSLETTER_SHAPE_PROFILES: dict[str, NewsletterShapeProfile] = {
    EVERY_TO_PROFILE.profile_id: EVERY_TO_PROFILE,
    TURING_POST_PROFILE.profile_id: TURING_POST_PROFILE,
}


def lookup_newsletter_shape_profile(
    from_header: str | None,
    original_url: str | None,
) -> NewsletterShapeProfile | None:
    email = normalize_sender_email(from_header)

    for profile in NEWSLETTER_SHAPE_PROFILES.values():
        if email is not None and email in profile.sender_emails:
            return profile
        if email is not None and profile.sender_domains:
            domain = email.rsplit("@", 1)[-1]
            if domain in profile.sender_domains:
                return profile

    if original_url:
        for profile in NEWSLETTER_SHAPE_PROFILES.values():
            if profile.allow_original_url_lookup and is_story_original_url(original_url, profile):
                return profile
    return None
