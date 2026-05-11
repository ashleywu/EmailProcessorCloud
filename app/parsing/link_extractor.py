"""Extract and classify anchors; resolve ``original_url`` (no ``subject``-titling tier)."""

from __future__ import annotations

from urllib.parse import parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.parsing import rules


def absolutize_html_url(base_doc: str, href: str) -> str | None:
    cleaned = href.strip()
    if not cleaned or cleaned.startswith("#"):
        return None
    joined = urljoin(base_doc or "", cleaned)
    parsed = urlparse(joined)
    if parsed.scheme not in {"http", "https"}:
        return None
    return joined.strip()


def _lower_host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def _path_low(url: str) -> str:
    try:
        return urlparse(url).path.lower()
    except ValueError:
        return ""


def is_social_navigation_url(url: str) -> bool:
    lowered = url.lower()
    return any(f in lowered for f in rules.SOCIAL_URL_FRAGMENTS)


def is_tracking_or_esp_navigation_url(url: str) -> bool:
    lh = _lower_host(url)
    lp = lh + _path_low(url)
    return any(n in lh or n in lp for n in rules.TRACKING_ORIGINAL_HOST_SUBSTRINGS)


def is_unsubscribe_or_footer_navigation(url: str, anchor_text_stripped: str) -> bool:
    path = _path_low(url)
    unsub_path_markers = (
        "unsubscribe",
        "opt-out",
        "optout",
        "preferences",
        "preference",
        "/sub/",
        "subscription",
        "lists",
        "/public/unsub",
        "list-unsubscribe",
    )
    if any(m in path for m in unsub_path_markers):
        return True

    if "mailto:" in url.lower():  # safety
        return anchor_text_stripped.lower() in rules.UNSUBSCRIBE_FOOTER_PHRASES

    qs_lower = urlparse(url).query.lower()
    if any(
        token in qs_lower
        for token in (
            "action=unsubscribe",
            "unsubscribe_token",
            "list_unsubscribe",
            "preference_token",
        )
    ):
        return True

    tl = anchor_text_stripped.strip().lower()
    if tl in {"unsubscribe", "manage preferences", "email preferences"}:
        return True
    return False


def excludes_navigation_noise(url: str, anchor_text_stripped: str) -> bool:
    """Signals navigation chrome (unsubscribe, ESP hops, bare social intents)."""

    if is_unsubscribe_or_footer_navigation(url, anchor_text_stripped):
        return True
    if is_tracking_or_esp_navigation_url(url):
        return True
    if is_social_navigation_url(url):
        return True
    return False


def excludes_original_url_candidate(url: str, anchor_text_stripped: str) -> bool:
    """Stricter filtering for picking a single authoritative article URL."""

    if excludes_navigation_noise(url, anchor_text_stripped):
        return True
    if rules.url_has_tracking_query(url):
        return True
    return False


def find_canonical_url(soup: BeautifulSoup, base_fallback: str) -> str | None:
    for tag in soup.find_all("link"):
        rel = tag.get("rel") or []
        parts = rel if isinstance(rel, (list, tuple)) else [rel]
        if not any(str(p).lower() == "canonical" for p in parts):
            continue
        href = tag.get("href")
        if not href:
            continue
        return absolutize_html_url(base_fallback or "", href)
    return None


def _normalize_anchor_visible_text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split())


def find_view_in_browser_url(soup: BeautifulSoup, base_fallback: str) -> str | None:
    for a in soup.find_all("a", href=True):
        text = _normalize_anchor_visible_text(a).casefold()
        if any(phrase.casefold() in text for phrase in rules.VIEW_IN_BROWSER_PHRASES):
            return absolutize_html_url(base_fallback or "", str(a["href"]))
    return None


def iter_anchor_hrefs_in_document_order(soup: BeautifulSoup) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        if isinstance(a, Tag):
            href = str(a["href"])
            txt = _normalize_anchor_visible_text(a)
            out.append((href, txt))
    return out


def resolve_original_url(
    soup: BeautifulSoup,
    *,
    base_fallback: str = "",
) -> str | None:
    """Pick article ``original_url`` without the deferred subject/title-anchor tier."""

    if (c := find_canonical_url(soup, base_fallback)) is not None:
        return c

    if (v := find_view_in_browser_url(soup, base_fallback)) is not None:
        return v

    for href_raw, txt in iter_anchor_hrefs_in_document_order(soup):
        absu = absolutize_html_url(base_fallback, href_raw)
        if absu is None:
            continue
        if excludes_original_url_candidate(absu, txt):
            continue
        return absu
    return None


def strip_tracking_noise_from_plain_url_line(url_text: str) -> str | None:
    """When a lone URL line is overwhelmingly tracking-params, suppress it."""

    if not rules.url_has_tracking_query(url_text):
        return url_text

    qs = urlparse(url_text.strip()).query
    if not qs:
        return url_text

    pairs = parse_qsl(qs, keep_blank_values=True)
    if not pairs:
        return url_text
    noisy = sum(
        1
        for k, _ in pairs
        if k.lower() in rules.TRACKING_QUERY_PARAM_NAMES
        or any(k.lower().startswith(p) for p in rules.TRACKING_QUERY_PARAM_PREFIXES)
    )
    if noisy >= len(pairs):
        return None
    return url_text


def collect_article_links_ordered(soup: BeautifulSoup, *, base_fallback: str) -> list[str]:
    """HTTP(S) links in reading order excluding obvious chrome noise."""

    seen: set[str] = set()
    ordered: list[str] = []
    for href_raw, txt in iter_anchor_hrefs_in_document_order(soup):
        url = absolutize_html_url(base_fallback, href_raw)
        if url is None:
            continue
        if excludes_navigation_noise(url, txt):
            continue
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered
