"""Parser + section invariants (see ``docs/section-extraction.md``)."""

from __future__ import annotations

from pathlib import Path

from app.models.section import EmailSection
from app.parsing.parser import parse_newsletter_html
from app.parsing.sectionizer import sectionize_newsletter_html

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _assert_email_section_contract(sec: EmailSection) -> None:
    assert sec.section_id
    assert isinstance(sec.order_index, int) and sec.order_index >= 0
    assert sec.text is not None
    assert isinstance(sec.links, list)
    assert isinstance(sec.image_urls, list)


def test_parse_newsletter_always_has_sections_and_section_count_matches() -> None:
    html = _fixture("email_sections_plain.html")
    parsed = parse_newsletter_html(html)
    assert len(parsed.sections) >= 1
    assert parsed.section_count == len(parsed.sections)
    for i, sec in enumerate(parsed.sections):
        _assert_email_section_contract(sec)
        assert sec.order_index == i
        assert sec.section_id == f"s{i}"


def test_fallback_exactly_one_section_when_no_headings_detected() -> None:
    html = _fixture("email_sections_plain.html")
    secs = sectionize_newsletter_html(html, base_hint="https://newsletter.example/")
    assert len(secs) == 1
    parsed = parse_newsletter_html(html)
    assert len(parsed.sections) == 1


def test_section_keeps_https_a_hrefs_in_section_links_minimal_anchor() -> None:
    html = """<html><body>
      <p><a href="https://canonical.example/asset">Label only</a></p>
    </body></html>"""
    secs = sectionize_newsletter_html(html)
    assert len(secs) == 1
    assert "https://canonical.example/asset" in secs[0].links


def test_section_keeps_img_src_url_in_section_image_urls_minimal_img() -> None:
    html = """<html><body>
      <p>Intro</p>
      <img src="https://cdn.example/asset/photo.png" alt="diagram" width="120" height="120"/>
    </body></html>"""
    secs = sectionize_newsletter_html(html)
    assert len(secs) == 1
    urls = secs[0].image_urls
    assert any(u.endswith("/asset/photo.png") for u in urls), urls


def test_section_links_retain_href_when_global_plain_text_unwraps_anchor() -> None:
    """Global ``plain_text`` uses anchor unwrapping; ``section.links`` must still carry https."""
    html = """<html><head>
      <base href="https://newsletter.example/issue/"/>
    </head><body>
      <p><a href="/story/unwrap-test">Read the story</a></p>
    </body></html>"""
    parsed = parse_newsletter_html(html)
    assert len(parsed.sections) == 1
    sec = parsed.sections[0]
    expected = "https://newsletter.example/story/unwrap-test"
    assert expected in sec.links
    assert parsed.plain_text.strip() == "Read the story"


def test_boilerplate_prune_keeps_article_links_images_inside_sections() -> None:
    html = _fixture("email_sections_body_plus_footer_boilerplate.html")
    parsed = parse_newsletter_html(html, base_hint="https://publisher.example/")
    kept = False
    for sec in parsed.sections:
        _assert_email_section_contract(sec)
        if any("/articles/victory-garden" in u for u in sec.links) and any(
            "garden-cover" in u for u in sec.image_urls
        ):
            kept = True
            assert not any("/legal/unsubscribe" in u for u in sec.links)
            break
    assert kept, "expected article link + hero image retained after pruning"
    unsub_in_any = any("/legal/unsubscribe" in u for s in parsed.sections for u in s.links)
    assert not unsub_in_any


def test_section_image_urls_survive_for_scoped_extraction() -> None:
    html = _fixture("email_sections_multi.html")
    parsed = parse_newsletter_html(html)
    tech = next(s for s in parsed.sections if s.heading and "Deep technical" in s.heading)
    assert any("chart.png" in u for u in tech.image_urls)
    assert tech.image_urls


def test_multi_section_each_has_distinct_section_id_and_order() -> None:
    html = _fixture("email_sections_multi.html")
    parsed = parse_newsletter_html(html)
    assert parsed.section_count == 3
    ids = [s.section_id for s in parsed.sections]
    assert ids == ["s0", "s1", "s2"]
    assert [s.order_index for s in parsed.sections] == [0, 1, 2]
    for s in parsed.sections:
        _assert_email_section_contract(s)
        assert s.heading is not None or "lead" in s.text.lower()
