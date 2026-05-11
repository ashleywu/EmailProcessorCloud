from __future__ import annotations

from pathlib import Path

from app.parsing.chunking import chunk_text
from app.parsing.parser import parse_newsletter_html

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_substack_fixture_keeps_canonical_and_scrubs_boilerplate() -> None:
    parsed = parse_newsletter_html(_fixture("substack_sample.html"))

    assert parsed.original_url == "https://your.substack.com/p/vector-databases"
    assert "https://your.substack.com/p/vector-databases?utm_medium=email" in parsed.links

    assert parsed.plain_text_chars == len(parsed.plain_text)
    assert "Deep dive on vector databases" in parsed.plain_text
    assert "Latency targets" in parsed.plain_text
    assert "- Latency targets" in parsed.plain_text
    assert "Unsubscribe" not in parsed.plain_text
    assert "privacy policy" not in parsed.plain_text.lower()

    assert "cdn.substack.com/images/arch-diagram.png" in parsed.image_urls[0]
    assert not any("facebook" in url for url in parsed.image_urls)
    assert not any("logo-footer" in url for url in parsed.image_urls)
    assert not any("pixel" in url or "track.gif" in url for url in parsed.image_urls)


def test_beehiiv_fixture_prefers_view_in_browser_over_body() -> None:
    parsed = parse_newsletter_html(_fixture("beehiiv_sample.html"))

    assert parsed.original_url == "https://mail.beehiiv.com/weekly/deep-dives/long-read-issue"
    assert "https://www.bloomberg.com/features/fusion-2026" in parsed.links


def test_every_fixture_strips_sponsor_copy_and_keeps_chart() -> None:
    parsed = parse_newsletter_html(_fixture("every_sample.html"))

    assert parsed.original_url == "https://every.to/chain-of-thought/chip-forecast"
    assert "every.to/uploads/chart-capacity.png" in "".join(parsed.image_urls)
    assert "CloudWidget" not in parsed.plain_text
    assert "Unsubscribe" not in parsed.plain_text


def test_original_url_canonical_beats_body_links() -> None:
    html = """
    <html><head>
      <link rel="canonical" href="https://canonical.example/post" />
    </head><body>
      <a href="https://body.example/other">Other</a>
    </body></html>
    """
    assert parse_newsletter_html(html).original_url == "https://canonical.example/post"


def test_original_url_prefers_view_when_canonical_missing() -> None:
    html = """
    <html><body>
      <a href="https://body.example/article?view=1">View in browser please</a>
      <a href="https://fallback.example/alt">Alt</a>
    </body></html>
    """
    assert parse_newsletter_html(html).original_url == "https://body.example/article?view=1"


def test_original_url_body_link_after_chrome() -> None:
    html = """
    <html><body>
      <a href="https://esp.example/opt-out/optout?id=123">quiet</a>
      <p>
        <a href="https://editorial.example/long-read">Hero story</a>
      </p>
    </body></html>
    """
    assert parse_newsletter_html(html).original_url == "https://editorial.example/long-read"


def test_original_url_none_when_only_chrome_links_exist() -> None:
    html = """
    <html><body>
      <a href="https://preferences.example/unsubscribe?token=zzz">Unsubscribe</a>
      <a href="https://facebook.com/sharer.php?u=https%3A%2F%2Fstory">Share</a>
    </body></html>
    """
    assert parse_newsletter_html(html).original_url is None


def test_plain_text_not_silently_truncated() -> None:
    long_copy = "Paragraph A\n\n" + ("word " * 2000)
    html = f"<html><body><p>{long_copy.replace(chr(10), '<br/>')}</p></body></html>"
    parsed = parse_newsletter_html(html)
    assert len(parsed.plain_text) > 5000
    assert parsed.plain_text_chars == len(parsed.plain_text)


def test_chunk_text_splits_on_paragraph_boundary() -> None:
    text = "First block\n\nSecond block\n\nThird block"
    chunks = chunk_text(text, max_chars=20)
    joined = "\n\n".join(chunks)
    assert "First block" in joined
    assert "Second block" in joined
    assert "Third block" in joined
    assert all(len(part) <= 20 for part in chunks)


def test_chunk_text_returns_empty_for_nonpositive_budget() -> None:
    assert chunk_text("hello", max_chars=0) == []
    assert chunk_text("hello", max_chars=-5) == []
