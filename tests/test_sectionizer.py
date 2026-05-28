"""Tests for DOM sectionization."""

from __future__ import annotations

from pathlib import Path

from app.parsing.parser import parse_newsletter_html
from app.parsing.sectionizer import heading_tags_in_document_order, sectionize_newsletter_html

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_heading_tags_ordered_by_dom_traversal() -> None:
    from app.parsing.sectionizer import _prepare_soup_for_sectioning

    html = _fixture("email_sections_multi.html")
    soup = _prepare_soup_for_sectioning(html)
    tags = heading_tags_in_document_order(soup)
    assert len(tags) == 2
    assert "Radar roundup" in tags[0].get_text()
    assert "Deep technical" in tags[1].get_text()


def test_multiple_sections_scope_links_and_follow_preamble_rules() -> None:
    html = _fixture("email_sections_multi.html")
    sections = sectionize_newsletter_html(html, base_hint="https://newsletter.example/")
    assert len(sections) == 3
    preamble, radar, tech = sections
    assert preamble.heading is None
    assert "lead-in" in preamble.text.lower()

    assert radar.heading == "Radar roundup"
    assert any(url.endswith("/radar/alpha") for url in radar.links)
    assert all("/tech/paper" not in u for u in radar.links)

    assert tech.heading is not None and "Deep technical" in tech.heading
    assert any(url.endswith("/tech/paper") for url in tech.links)
    imgs = tech.image_urls
    assert imgs, "Hero image missing from scoped extraction"
    assert any("chart.png" in u for u in imgs)


def test_fallback_single_section_when_no_headings() -> None:
    html = _fixture("email_sections_plain.html")
    secs = sectionize_newsletter_html(html, base_hint="https://newsletter.example/")
    assert len(secs) == 1
    solo = secs[0]
    assert solo.order_index == 0
    assert solo.section_id == "s0"
    assert "solo link".lower() in solo.text.lower() or solo.links


def test_parse_newsletter_populates_sections() -> None:
    html = _fixture("email_sections_multi.html")
    parsed = parse_newsletter_html(html)
    assert len(parsed.sections) == 3
    assert parsed.section_count == 3
    assert parsed.sections[1].heading == "Radar roundup"
