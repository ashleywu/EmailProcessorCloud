"""Centralized heuristics for HTML email parsing — keep literals out of call sites."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

# Visible anchor / block text implying unsubscribe or legal footer noise.
UNSUBSCRIBE_FOOTER_PHRASES: frozenset[str] = frozenset(
    {
        "unsubscribe",
        "manage preferences",
        "email preferences",
        "update subscription",
        "preference center",
        "opt out",
        "do not wish to receive",
        "privacy policy",
        "terms of service",
        "terms & conditions",
        "you are receiving this email",
        "this email was sent to",
        "list-unsubscribe",
    }
)

# Anchor text snippets for secondary original_url tier.
VIEW_IN_BROWSER_PHRASES: frozenset[str] = frozenset(
    {
        "view in browser",
        "open in browser",
        "see this email in your browser",
        "read online",
        "view online",
        "open online",
        "can't see this email?",
        "can’t see this email?",
        "having trouble viewing",
    }
)

TRACKING_QUERY_PARAM_PREFIXES: tuple[str, ...] = (
    "utm_",
    "spm",
    "_hsenc",
    "_hsmi",
)

TRACKING_QUERY_PARAM_NAMES: frozenset[str] = frozenset(
    {
        "mc_cid",
        "mc_eid",
        "mkt_tok",
        "igshid",
        "fbclid",
        "gclid",
        "msclkid",
        "pk_campaign",
        "pk_kwd",
        "oref",
        "ref",
        "ref_src",
        "spm",
        "si",
        "subscriber_id",
        "subscriberid",
        "token",
        "verification",
        "campaign_id",
    }
)


def url_has_tracking_query(raw_url: str) -> bool:
    """True when query string looks dominated by click/analytics tracking parameters."""

    if not raw_url or not raw_url.strip():
        return False
    qs = urlparse(raw_url).query.lower()
    if not qs:
        return False

    pairs = parse_qsl(qs, keep_blank_values=True)
    if not pairs:
        return False

    tracking_hits = 0
    for key, _val in pairs:
        kl = key.lower()
        if kl in TRACKING_QUERY_PARAM_NAMES or any(kl.startswith(p) for p in TRACKING_QUERY_PARAM_PREFIXES):
            tracking_hits += 1

    return tracking_hits >= max(2, len(pairs))


# Host substring hints for redirects / trackers (lowercase needle).
TRACKING_HOST_SUBSTRINGS: tuple[str, ...] = (
    "googletagmanager",
    "google-analytics",
    "doubleclick",
    "facebook.com/tr",
    "pxl.",
    "open.",
    "clicks.mail",
    "click.",
    "track.",
    "trk.",
    "link.mail.",
    "list-manage.com",
)

# Typical ESP / footer host fragments — treat like tracking for ``original_url`` only.
TRACKING_ORIGINAL_HOST_SUBSTRINGS: tuple[str, ...] = TRACKING_HOST_SUBSTRINGS + (
    "preference-center",
    "subscriptions.",
)


# Paths or hosts suggesting social icons / share badges (URLs lowercased before check).
SOCIAL_URL_FRAGMENTS: tuple[str, ...] = (
    "facebook.com/",
    "fb.com/",
    "twitter.com/",
    "x.com/",
    "linkedin.com/",
    "instagram.com/",
    "youtube.com/",
    "tiktok.com/",
    "/share?url=",
    "addtoany",
    "/widgets/share",
)


# Narrow logo / avatar / icon noise in asset URLs or filenames.
LOGO_AVATAR_URL_KEYWORDS: tuple[str, ...] = (
    "logo",
    "avatar",
    "favicon",
    "badge",
    "/icon",
    "_icon.",
    "-icon.",
    "social-share",
)


LOGO_AVATAR_ALT_SUBSTRINGS: tuple[str, ...] = (
    "logo",
    "avatar",
    "twitter",
    "facebook",
    "linkedin",
)


# Sponsor / muted legal blocks sometimes ship with recognizable class crumbs.
SPONSOR_CLASS_SUBSTRINGS: tuple[str, ...] = (
    "sponsor",
    "native-ad",
    "promoted",
    "advertisement",
)


# Structural hints for peeling off layout chrome / boilerplate wrappers.
FOOTER_CLASS_ID_SUBSTRINGS: tuple[str, ...] = (
    "footer",
    "mastfoot",
    "email-footer",
    "mail_footer",
)


FOOTER_ROLE_VALUES: frozenset[str] = frozenset({"contentinfo"})


MIN_MEANINGFUL_IMAGE_EDGE_PX: int = 8

TRACKING_PIXEL_MAX_EDGE_PX: int = 3
