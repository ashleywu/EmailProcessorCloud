"""High-level façade for turning raw newsletter HTML into structured fields."""

from __future__ import annotations

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, computed_field

from app.models.section import EmailSection
from app.parsing.chunking import chunk_text
from app.parsing.html_cleaner import html_to_plaintext_soup
from app.parsing.image_extractor import collect_ranked_images
from app.parsing.link_extractor import (
    absolutize_html_url,
    collect_article_links_ordered,
    find_canonical_url,
    resolve_original_url,
)
from app.parsing.sectionizer import sectionize_newsletter_html


class ParsedHtmlResult(BaseModel):
    """Structured crawl of a newsletter's HTML envelope.

    Section-scoped semantics (authoritative URLs per slice vs ``plain_text`` limitations)
    are documented in ``docs/section-extraction.md``.

    ``plain_text`` is never forcibly shortened here; LLM ingestion code must inspect
    ``plain_text_chars`` against its model window and funnel content through ``chunk_text`` ahead
    of each completion call whenever necessary.
    """

    plain_text: str = Field(..., description="Paragraph-oriented plaintext scrubbed for chrome noise.")
    plain_text_chars: int = Field(..., ge=0, description="Unicode codepoint length of ``plain_text``.")
    links: list[str]
    image_urls: list[str]
    original_url: str | None = None
    sections: list[EmailSection] = Field(
        default_factory=list,
        description="DOM-derived reading-order sections for segmented routing.",
    )

    @computed_field
    @property
    def section_count(self) -> int:
        """Cardinality of ``sections`` (always ``>= 1`` when built via ``parse_newsletter_html``)."""
        return len(self.sections)


def _resolve_document_base(soup: BeautifulSoup) -> str:
    for tag in soup.find_all("base", href=True):
        href = str(tag.get("href") or "").strip()
        normalized = absolutize_html_url("", href)
        if normalized:
            return normalized
        if href.startswith("//"):
            return absolutize_html_url("https:", href) or ""

    canon = find_canonical_url(soup, "")
    if canon:
        return canon
    return ""


def parse_newsletter_html(
    html: str,
    *,
    base_hint: str | None = None,
) -> ParsedHtmlResult:
    """Turn raw HTML email markup into ingestion-ready payloads."""

    # Structured extraction must run on a pristine tree — html_cleaner replaces <img> nodes and
    # similar, which would invalidate image scraping if it ran first on the shared soup instance.
    soup = BeautifulSoup(html, "html.parser")
    doc_base = (base_hint or "").strip() or _resolve_document_base(soup)

    original_url = resolve_original_url(soup, base_fallback=doc_base)
    ordered_links = collect_article_links_ordered(soup, base_fallback=doc_base)
    hero_images = collect_ranked_images(soup, base_fallback=doc_base)

    plain_soup = BeautifulSoup(html, "html.parser")
    plaintext = html_to_plaintext_soup(plain_soup)

    sections = sectionize_newsletter_html(html, base_hint=doc_base)
    if not sections:
        raise RuntimeError("sectionizer invariant violated: expected >= 1 section")

    return ParsedHtmlResult(
        plain_text=plaintext,
        plain_text_chars=len(plaintext),
        links=ordered_links,
        image_urls=hero_images,
        original_url=original_url,
        sections=sections,
    )


__all__ = ["ParsedHtmlResult", "chunk_text", "parse_newsletter_html"]
