"""Primary story URL normalization (profile-driven)."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import parse_qs, unquote, urlparse

from app.models.section import EmailSection
from app.processing.newsletter_shape.profile import NewsletterShapeProfile, PrimaryUrlRules

_BEEHIiv_HOST_FRAGMENT = "beehiiv.com"


def unwrap_tracking_url(url: str, rules: PrimaryUrlRules) -> str:
    cleaned = str(url or "").strip()
    if not cleaned:
        return cleaned

    parsed = urlparse(cleaned)
    host = parsed.netloc.lower()

    for rule in rules.tracking_unwrap:
        if host not in rule.tracking_hosts:
            continue
        path = parsed.path or ""
        lowered = path.lower()
        for marker in rule.path_markers:
            idx = lowered.find(marker)
            if idx == -1:
                continue
            embedded = unquote(path[idx + len(marker) :]).strip()
            if embedded.startswith("http://") or embedded.startswith("https://"):
                return embedded

    if _BEEHIiv_HOST_FRAGMENT in host:
        qs = parse_qs(parsed.query)
        for key in rules.beehiiv_query_keys:
            values = qs.get(key)
            if not values:
                continue
            candidate = unquote(str(values[0]).strip())
            if candidate.startswith("http://") or candidate.startswith("https://"):
                return candidate

    return cleaned


def _strip_query_for_compare(url: str, rules: PrimaryUrlRules) -> str:
    parsed = urlparse(url)
    if not parsed.query:
        return url
    kept: list[str] = []
    for part in parsed.query.split("&"):
        if not part:
            continue
        name = part.split("=", 1)[0].lower()
        if name in rules.strip_query_names:
            continue
        if any(name.startswith(prefix) for prefix in rules.strip_query_prefixes):
            continue
        kept.append(part)
    query = "&".join(kept)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    return f"{base}?{query}" if query else base


def canonical_story_path(url: str, profile: NewsletterShapeProfile) -> str | None:
    rules = profile.primary_url
    unwrapped = unwrap_tracking_url(url, rules)
    unwrapped = _strip_query_for_compare(unwrapped, rules)
    parsed = urlparse(unwrapped)
    host = parsed.netloc.lower()
    if host not in rules.article_hosts:
        return None

    path = (parsed.path or "").rstrip("/").lower()
    if not path or path == "/":
        return None
    for prefix in rules.non_article_path_prefixes:
        if path.startswith(prefix):
            return None
    if not any(pattern.match(path) for pattern in rules.story_path_patterns):
        return None
    return f"{host}{path}"


def is_story_original_url(original_url: str | None, profile: NewsletterShapeProfile) -> bool:
    return original_url is not None and canonical_story_path(original_url, profile) is not None


def _canonical_from_original(original_url: str | None, profile: NewsletterShapeProfile) -> str | None:
    if not original_url:
        return None
    return canonical_story_path(original_url, profile)


def _same_story(path: str, canonical: str | None) -> bool:
    if canonical is None:
        return False
    if path == canonical:
        return True
    path_slug = path.rsplit("/", 1)[-1]
    canon_slug = canonical.rsplit("/", 1)[-1]
    return bool(path_slug and path_slug == canon_slug)


def section_canonical_story_paths(
    section: EmailSection,
    profile: NewsletterShapeProfile,
) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for link in section.links:
        path = canonical_story_path(str(link), profile)
        if path is not None and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def dominant_section_story_path(
    section: EmailSection,
    profile: NewsletterShapeProfile,
    *,
    canonical: str | None,
) -> str | None:
    paths = section_canonical_story_paths(section, profile)
    if not paths:
        return None
    if len(paths) == 1:
        return paths[0]
    counts: dict[str, int] = {}
    for link in section.links:
        path = canonical_story_path(str(link), profile)
        if path is None:
            continue
        counts[path] = counts.get(path, 0) + 1
    if not counts:
        return None
    best_path, best_count = max(counts.items(), key=lambda item: item[1])
    total = sum(counts.values())
    if best_count / total >= 0.5:
        return best_path
    if canonical is not None and canonical in counts:
        return canonical
    return None


def collect_distinct_canonical_story_urls(
    sections: Sequence[EmailSection],
    *,
    original_url: str | None,
    profile: NewsletterShapeProfile,
) -> set[str]:
    canonical = _canonical_from_original(original_url, profile)
    story_paths: set[str] = set()

    for section in sections:
        for path in section_canonical_story_paths(section, profile):
            if canonical is not None and _same_story(path, canonical):
                story_paths.add(canonical)
            else:
                story_paths.add(path)

    if not story_paths and canonical is not None:
        story_paths.add(canonical)
    return story_paths


def effective_primary_url_count(
    sections: Sequence[EmailSection],
    *,
    original_url: str | None,
    profile: NewsletterShapeProfile | None,
) -> int:
    if profile is not None:
        return len(
            collect_distinct_canonical_story_urls(
                sections,
                original_url=original_url,
                profile=profile,
            ),
        )

    seen: set[str] = set()
    for section in sections:
        for link in section.links:
            url = str(link).strip()
            if url.startswith("https://") and url not in seen:
                seen.add(url)
    return len(seen)
