"""Image asset extraction tuned for newsletters (drops pixels + social/chrome)."""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from app.parsing import rules
from app.parsing.link_extractor import absolutize_html_url


@dataclass(frozen=True)
class RankedImage:
    url: str
    pixel_area: int


def _parse_dim(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower().rstrip("px").strip("%")
    if not text:
        return None
    accum = []
    dot_seen = False
    for ch in text:
        if ch.isdigit():
            accum.append(ch)
        elif ch == "." and not dot_seen:
            dot_seen = True
            accum.append(ch)
        else:
            break
    if not accum:
        return None
    try:
        parsed = float("".join(accum))
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return int(parsed)


def _parse_srcset_largest(candidate: str) -> str | None:
    picks: list[tuple[int, str]] = []
    for chunk in candidate.split(","):
        part = chunk.strip()
        if not part:
            continue
        segments = part.split()
        url = segments[0]
        width = None
        for seg in segments[1:]:
            if seg.endswith("w"):
                try:
                    width = int(seg[:-1])
                except ValueError:
                    width = None
        picks.append((width or 1, url))
    if not picks:
        return None
    picks.sort(key=lambda tpl: tpl[0], reverse=True)
    return picks[0][1]


def _image_area(img: Tag) -> int | None:
    w = _parse_dim(img.get("width"))
    h = _parse_dim(img.get("height"))
    if w is None or h is None:
        return None
    return max(1, w * h)


def _looks_like_tracking_pixel(img: Tag, url: str) -> bool:
    w = _parse_dim(img.get("width"))
    h = _parse_dim(img.get("height"))
    lc = url.lower()
    hints = ("pixel", "/spacer", "/track", "/open/", "tracking", "analytics", "_px.")
    pixelish = False
    if w is not None and h is not None:
        if w <= rules.TRACKING_PIXEL_MAX_EDGE_PX and h <= rules.TRACKING_PIXEL_MAX_EDGE_PX:
            pixelish = True
    if "/1x1" in lc or "1x1" in lc.replace("×", "x"):
        pixelish = True
    if any(hit in lc for hit in hints):
        pixelish = True
    return pixelish


def _is_logo_or_icon(url: str, alt: str) -> bool:
    merged = (url.lower() + " " + alt.lower()).lower()
    return any(hit in merged for hit in rules.LOGO_AVATAR_URL_KEYWORDS) or any(
        hit in merged for hit in rules.LOGO_AVATAR_ALT_SUBSTRINGS
    )


def _is_social_or_cd_image(url: str) -> bool:
    lower = url.lower()
    return any(hit in lower for hit in rules.SOCIAL_URL_FRAGMENTS)


def _below_meaningful_floor(img: Tag) -> bool:
    w = _parse_dim(img.get("width"))
    h = _parse_dim(img.get("height"))
    if w is None or h is None:
        return False
    return (
        min(w, h) < rules.MIN_MEANINGFUL_IMAGE_EDGE_PX
        and max(w, h) < rules.MIN_MEANINGFUL_IMAGE_EDGE_PX * 6
    )


def collect_ranked_images(soup: BeautifulSoup, *, base_fallback: str) -> list[str]:
    ranked: list[RankedImage] = []

    for img in soup.find_all("img"):
        if not isinstance(img, Tag):
            continue

        raw_src = str(img.get("src") or "").strip()
        candidates: list[str] = []
        if raw_src:
            candidates.append(raw_src)
        srcset = str(img.get("srcset") or "").strip()
        if srcset:
            choice = _parse_srcset_largest(srcset)
            if choice:
                candidates.append(choice)

        alt = str(img.get("alt") or "")

        for raw in candidates:
            abs_u = absolutize_html_url(base_fallback or "", raw)
            if abs_u is None:
                continue
            if _is_social_or_cd_image(abs_u):
                continue
            if _is_logo_or_icon(abs_u, alt):
                continue
            if _looks_like_tracking_pixel(img, abs_u):
                continue
            if _below_meaningful_floor(img):
                continue

            area = _image_area(img) or 10_000
            ranked.append(RankedImage(abs_u, pixel_area=max(area, 1)))

    ranked.sort(key=lambda item: (-item.pixel_area, item.url))
    seen: set[str] = set()
    ordered: list[str] = []
    for item in ranked:
        if item.url not in seen:
            seen.add(item.url)
            ordered.append(item.url)
    return ordered
