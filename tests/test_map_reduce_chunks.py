from __future__ import annotations

from app.models.section import EmailSection
from app.parsing.map_reduce_chunks import chunk_sections_for_map


def _many_sections(count: int, *, chars: int = 400) -> list[EmailSection]:
    filler = "x" * chars
    return [
        EmailSection(
            section_id=f"s{i}",
            order_index=i,
            heading=f"Story {i}",
            text=f"{filler} section-{i}",
            links=[],
            image_urls=[],
        )
        for i in range(count)
    ]


def test_twenty_plus_sections_caps_chunk_count() -> None:
    chunks = chunk_sections_for_map(
        _many_sections(22),
        target_chars=14000,
        max_chunks=6,
    )
    assert 1 <= len(chunks) <= 6


def test_oversized_section_stays_single_chunk() -> None:
    big = EmailSection(
        section_id="s0",
        order_index=0,
        heading="Huge",
        text="y" * 20000,
        links=[],
        image_urls=[],
    )
    small = EmailSection(
        section_id="s1",
        order_index=1,
        heading="Small",
        text="z" * 100,
        links=[],
        image_urls=[],
    )
    chunks = chunk_sections_for_map(
        [big, small],
        target_chars=14000,
        max_chunks=6,
    )
    assert any("Huge" in c.text and "y" * 1000 in c.text for c in chunks)
    assert len(chunks) <= 6


def test_chunk_text_preserves_headings() -> None:
    secs = _many_sections(3, chars=50)
    chunks = chunk_sections_for_map(secs, target_chars=14000, max_chunks=6)
    assert "## Story 0" in chunks[0].text
