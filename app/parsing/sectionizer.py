"""DOM-based splitting of newsletter HTML into ordered ``EmailSection`` slices.

Contracts: the sectionizer **preserves** ``<a href>`` (no anchor unwrapping) and **preserves**
``<img>`` (no media-to-text replacement) so ``EmailSection.links`` / ``image_urls`` stay
authoritative per slice; see ``docs/section-extraction.md``.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from bs4 import BeautifulSoup, NavigableString, Tag

from app.models.section import EmailSection
from app.parsing.html_cleaner import (
    _collapse_block_breaks,
    html_to_plaintext,
    prune_newsletter_boilerplate,
    scrub_plainnoise_lines,
)
from app.parsing.image_extractor import (
    RankedImage,
    _below_meaningful_floor,
    _image_area,
    _is_logo_or_icon,
    _is_social_or_cd_image,
    _looks_like_tracking_pixel,
    _parse_srcset_largest,
)
from app.parsing.link_extractor import (
    absolutize_html_url,
    collect_article_links_ordered,
    excludes_navigation_noise,
)

_HEADING_NAMES = frozenset({f"h{i}" for i in range(1, 7)})

_MD_HEADING_CLASS_HINTS = frozenset(
    {
        "md-heading",
        "markdown-heading",
        "markdown-h1",
        "markdown-h2",
        "markdown-h3",
    }
)


def _is_heading_tag(tag: Tag | None) -> bool:
    if tag is None or not isinstance(tag, Tag):
        return False
    name = tag.name.lower()
    if name in _HEADING_NAMES:
        return True
    if name.startswith("md-h") and len(name) == 5 and name[-1].isdigit():
        return True
    classes = tag.get("class") or []
    class_blob = " ".join(str(c).lower() for c in classes if isinstance(c, str))
    role = str(tag.get("role") or "").lower()
    if role == "heading" and len(tag.get_text(strip=True)) >= 3:
        return True
    return any(hit in class_blob for hit in _MD_HEADING_CLASS_HINTS)


def _heading_display_text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split())


def _prepare_soup_for_sectioning(html: str) -> BeautifulSoup:
    """Chrome-strip like plaintext prep while retaining ``<a>`` tags for per-section URLs."""

    soup = BeautifulSoup(html, "html.parser")
    prune_newsletter_boilerplate(soup)
    return soup


def _document_start_leaf(soup: BeautifulSoup) -> Tag | NavigableString | None:
    root = soup.body
    if root is None:
        root = soup
    inner = getattr(root, "next_element", None)
    while inner is not None and not isinstance(inner, (Tag, NavigableString)):
        inner = getattr(inner, "next_element", None)
    while isinstance(inner, NavigableString) and not str(inner).strip():
        inner = getattr(inner, "next_element", None)
    return inner


def iter_nodes_inclusive_exclusive(
    start: Tag | NavigableString | None,
    stop: Tag | NavigableString | None,
) -> Iterator[Tag | NavigableString]:
    """Walk ``next_element`` order from ``start``; stop before visiting ``stop``."""

    if start is None:
        return
    cur: Tag | NavigableString | None = start
    while cur is not None:
        if stop is not None and cur is stop:
            break
        yield cur
        nxt = getattr(cur, "next_element", None)
        if nxt is None:
            break
        if stop is not None and nxt is stop:
            break
        cur = nxt


def _plain_from_nodes(nodes: Sequence[Tag | NavigableString]) -> str:
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, NavigableString):
            parent = getattr(node, "parent", None)
            pname = getattr(parent, "name", None)
            if pname in {"script", "style"}:
                continue
            piece = str(node).strip()
            if piece:
                parts.append(piece)
    collapsed = "\n".join(parts)
    tidy = scrub_plainnoise_lines(_collapse_block_breaks(collapsed))
    tidy = tidy.replace("\u00a0", " ")
    tidy = "\n".join(line.rstrip() for line in tidy.splitlines()).strip()
    return tidy


def _links_from_nodes(
    nodes: Sequence[Tag | NavigableString],
    *,
    base_fallback: str,
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for node in nodes:
        if isinstance(node, Tag) and node.name.lower() == "a" and node.has_attr("href"):
            href_raw = str(node.get("href") or "")
            txt = " ".join(node.get_text(" ", strip=True).split())
            url = absolutize_html_url(base_fallback, href_raw)
            if url is None:
                continue
            if excludes_navigation_noise(url, txt):
                continue
            if url not in seen:
                seen.add(url)
                ordered.append(url)
    return ordered


def _ranked_images_from_nodes(
    nodes: Sequence[Tag | NavigableString],
    *,
    base_fallback: str,
) -> list[str]:
    ranked: list[RankedImage] = []
    seen_img: set[int] = set()
    for node in nodes:
        if not isinstance(node, Tag) or node.name.lower() != "img":
            continue
        nid = id(node)
        if nid in seen_img:
            continue
        seen_img.add(nid)

        raw_src = str(node.get("src") or "").strip()
        candidates: list[str] = []
        if raw_src:
            candidates.append(raw_src)
        srcset = str(node.get("srcset") or "").strip()
        if srcset:
            choice = _parse_srcset_largest(srcset)
            if choice:
                candidates.append(choice)

        alt = str(node.get("alt") or "")
        for raw in candidates:
            abs_u = absolutize_html_url(base_fallback or "", raw)
            if abs_u is None:
                continue
            if _is_social_or_cd_image(abs_u):
                continue
            if _is_logo_or_icon(abs_u, alt):
                continue
            if _looks_like_tracking_pixel(node, abs_u):
                continue
            if _below_meaningful_floor(node):
                continue

            area = _image_area(node) or 10_000
            ranked.append(RankedImage(abs_u, pixel_area=max(area, 1)))

    ranked.sort(key=lambda item: (-item.pixel_area, item.url))
    seen_urls: set[str] = set()
    ordered: list[str] = []
    for item in ranked:
        if item.url not in seen_urls:
            seen_urls.add(item.url)
            ordered.append(item.url)
    return ordered


def heading_tags_in_document_order(soup: BeautifulSoup) -> list[Tag]:
    start = _document_start_leaf(soup)
    if start is None:
        return []
    ordered: list[Tag] = []
    seen: set[int] = set()
    for node in iter_document_order_from(start):
        if not isinstance(node, Tag):
            continue
        if not _is_heading_tag(node):
            continue
        nid = id(node)
        if nid in seen:
            continue
        seen.add(nid)
        if len(_heading_display_text(node).strip()) < 2:
            continue
        ordered.append(node)
    return ordered


def iter_document_order_from(start: Tag | NavigableString) -> Iterator[Tag | NavigableString]:
    cur: Tag | NavigableString | None = start
    while cur is not None:
        yield cur
        cur = getattr(cur, "next_element", None)


def sectionize_newsletter_html(
    html: str,
    *,
    base_hint: str = "",
    email_id: str | None = None,
) -> list[EmailSection]:
    """Return ≥1 sections; headings split slices, otherwise one section for the whole email."""

    doc_base = (base_hint or "").strip()
    soup = _prepare_soup_for_sectioning(html)
    headings = heading_tags_in_document_order(soup)

    if not headings:
        return [_whole_document_section(html, doc_base=doc_base, email_id=email_id)]

    sections: list[EmailSection] = []
    first_h = headings[0]
    preamble_leaf = _document_start_leaf(soup)

    preamble_nodes = (
        list(iter_nodes_inclusive_exclusive(preamble_leaf, first_h))
        if preamble_leaf is not None
        else []
    )
    preamble_plain = _plain_from_nodes(preamble_nodes)
    if preamble_plain.strip():
        sections.append(
            EmailSection(
                section_id="s0",
                order_index=0,
                heading=None,
                text=preamble_plain,
                links=_links_from_nodes(preamble_nodes, base_fallback=doc_base),
                image_urls=_ranked_images_from_nodes(preamble_nodes, base_fallback=doc_base),
                email_id=email_id,
            )
        )

    offset = len(sections)

    for i, h_tag in enumerate(headings):
        nxt = headings[i + 1] if i + 1 < len(headings) else None
        span_nodes = list(iter_nodes_inclusive_exclusive(h_tag, nxt))
        h_text = _heading_display_text(h_tag)
        oid = offset + i
        sections.append(
            EmailSection(
                section_id=f"s{oid}",
                order_index=oid,
                heading=h_text or None,
                text=_plain_from_nodes(span_nodes),
                links=_links_from_nodes(span_nodes, base_fallback=doc_base),
                image_urls=_ranked_images_from_nodes(span_nodes, base_fallback=doc_base),
                email_id=email_id,
            )
        )

    if sections:
        return sections
    return [_whole_document_section(html, doc_base=doc_base, email_id=email_id)]


def _whole_document_section(
    html: str,
    *,
    doc_base: str,
    email_id: str | None,
) -> EmailSection:
    soup_clean = _prepare_soup_for_sectioning(html)
    pruned_base = doc_base or _infer_base(html, soup_clean)
    text = html_to_plaintext(html).strip()
    links = collect_article_links_ordered(soup_clean, base_fallback=pruned_base)
    imgs = _rank_images_whole_mail(soup_clean, base_fallback=pruned_base)
    return EmailSection(
        section_id="s0",
        order_index=0,
        heading=None,
        text=text,
        links=links,
        image_urls=imgs,
        email_id=email_id,
    )


def _infer_base(_html: str, soup: BeautifulSoup) -> str:
    from app.parsing.link_extractor import find_canonical_url

    for tag in soup.find_all("base", href=True):
        href = str(tag.get("href") or "").strip()
        u = absolutize_html_url("", href)
        if u:
            return u
        if href.startswith("//"):
            return absolutize_html_url("https:", href) or ""
    c = find_canonical_url(soup, "")
    return c or ""


def _rank_images_whole_mail(soup: BeautifulSoup, *, base_fallback: str) -> list[str]:
    from app.parsing.image_extractor import collect_ranked_images

    return collect_ranked_images(soup, base_fallback=base_fallback)


__all__ = [
    "heading_tags_in_document_order",
    "sectionize_newsletter_html",
]
