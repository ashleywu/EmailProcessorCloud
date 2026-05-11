"""Strip newsletter chrome/spam from HTML prior to plaintext extraction."""

from __future__ import annotations

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from app.parsing import rules
from app.parsing.link_extractor import strip_tracking_noise_from_plain_url_line


def _tag_attr_blob(tag: Tag) -> str:
    attrs = getattr(tag, "attrs", None)
    if not isinstance(attrs, dict):
        return ""
    classes = attrs.get("class") or ()
    blob = (
        tag.name.lower(),
        *(str(c).lower() for c in classes if isinstance(c, str)),
        str(attrs.get("id") or "").lower(),
        str(attrs.get("role") or "").lower(),
    )
    return " ".join(blob)


def _should_drop_footerish(tag: Tag) -> bool:
    blob = _tag_attr_blob(tag)
    return any(hit in blob for hit in rules.FOOTER_CLASS_ID_SUBSTRINGS)


def _should_drop_sponsor(tag: Tag) -> bool:
    blob = _tag_attr_blob(tag)
    return any(hit in blob for hit in rules.SPONSOR_CLASS_SUBSTRINGS)


def _inherits_footer_role(tag: Tag) -> bool:
    """Walk ancestors for ``role=contentinfo`` (footer landmark)."""

    cur: Tag | None = tag
    while cur is not None:
        attrs = getattr(cur, "attrs", None)
        role = ""
        if isinstance(attrs, dict):
            role = str(attrs.get("role") or "").strip().lower()
        if role in rules.FOOTER_ROLE_VALUES:
            return True
        parent = cur.parent
        cur = parent if isinstance(parent, Tag) else None
    return False


def prune_newsletter_boilerplate(soup: BeautifulSoup) -> None:
    """Destructively peel obvious sponsor/footer shells before text extraction."""

    for tag in list(soup.find_all(string=lambda t: isinstance(t, Comment))):
        tag.extract()

    for tag in list(soup.find_all(["script", "style", "noscript"])):
        if isinstance(tag, Tag):
            tag.decompose()

    for tag in tuple(soup.find_all(True)):  # type: ignore[arg-type]
        if not isinstance(tag, Tag):
            continue
        attrs = getattr(tag, "attrs", None)
        if not isinstance(attrs, dict):
            tag.decompose()
            continue
        if tag.name.lower() == "link":
            continue
        if tag.name.lower() == "meta":
            tag.decompose()
            continue
        if _should_drop_footerish(tag) or _should_drop_sponsor(tag) or _inherits_footer_role(tag):
            tag.decompose()
            continue

        # Lightweight unsubscribe micro-rows: anchors only.
        if tag.name.lower() == "a" and tag.has_attr("href"):
            href = str(tag.get("href") or "")
            lowered = href.lower()
            if "mailto:list-unsubscribe" in lowered:
                tag.decompose()


def _replace_media_with_readable_spans(soup: BeautifulSoup) -> None:
    for img in list(soup.find_all("img")):
        if not isinstance(img, Tag):
            continue
        attrs = getattr(img, "attrs", None)
        if not isinstance(attrs, dict):
            img.decompose()
            continue
        alt = str(img.get("alt") or "").strip()
        if alt:
            img.replace_with(NavigableString(alt + "\n"))
        else:
            img.decompose()


def _unwrap_navigation_links_into_text(soup: BeautifulSoup) -> None:
    for a in list(soup.find_all("a")):
        if not isinstance(a, Tag):
            continue
        text = " ".join(a.get_text(" ", strip=True).split())
        replacement = NavigableString(text + "\n") if text else NavigableString("")
        a.replace_with(replacement)


def _collapse_block_breaks(raw: str) -> str:
    lines = []
    buf: list[str] = []
    for block in raw.split("\n"):
        piece = block.strip()
        if not piece:
            if buf:
                lines.append(" ".join(buf))
                buf = []
            continue
        buf.append(piece)
    if buf:
        lines.append(" ".join(buf))
    collapsed = "\n".join(lines)
    return "\n".join(line.strip() for line in collapsed.splitlines() if line.strip())


def scrub_plainnoise_lines(raw: str) -> str:
    filtered: list[str] = []

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()

        if lowered.startswith(("http://", "https://")):
            if strip_tracking_noise_from_plain_url_line(stripped) is None:
                continue

        if len(stripped) <= 140:
            if any(p in lowered for p in rules.UNSUBSCRIBE_FOOTER_PHRASES):
                continue

        filtered.append(stripped)

    return "\n".join(filtered)


def html_to_plaintext_soup(soup: BeautifulSoup) -> str:
    """Mutate ``soup`` in place and return cleaned plaintext (use a throwaway parse tree only)."""

    prune_newsletter_boilerplate(soup)
    _replace_media_with_readable_spans(soup)
    _unwrap_navigation_links_into_text(soup)

    for li in list(soup.find_all("li")):
        if not isinstance(li, Tag):
            continue
        text_part = li.get_text(" ", strip=True)
        li.replace_with(NavigableString(f"- {text_part}\n"))

    text = soup.get_text("\n", strip=True)

    tidy = scrub_plainnoise_lines(_collapse_block_breaks(text))
    tidy = tidy.replace("\u00a0", " ")
    tidy = "\n".join(line.rstrip() for line in tidy.splitlines())
    tidy = tidy.strip()
    return tidy


def html_to_plaintext(html: str) -> str:
    """Return prose-oriented plaintext with bullets preserved as ``- `` lines."""

    return html_to_plaintext_soup(BeautifulSoup(html, "html.parser"))
