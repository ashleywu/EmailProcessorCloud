from __future__ import annotations

from app.models.section import EmailSection
from app.parsing.ainews_boundaries import (
    is_recap_boundary_heading,
    split_ainews_sections,
)


def _sec(i: int, heading: str | None, text: str = "body") -> EmailSection:
    return EmailSection(
        section_id=f"s{i}",
        order_index=i,
        heading=heading,
        text=text,
        links=[],
        image_urls=[],
    )


def test_ai_twitter_recap_splits_hero_and_recap() -> None:
    sections = [
        _sec(0, "Reve 2 and Ideogram 4: Layouts in Imagegen", "hero"),
        _sec(1, "AI Twitter Recap", "twitter"),
        _sec(2, "AI Reddit Recap", "reddit"),
    ]
    split = split_ainews_sections(sections)
    assert split.has_boundary is True
    assert [s.heading for s in split.hero_sections] == [
        "Reve 2 and Ideogram 4: Layouts in Imagegen",
    ]
    assert [s.heading for s in split.recap_sections] == [
        "AI Twitter Recap",
        "AI Reddit Recap",
    ]


def test_boundary_section_is_included_in_recap() -> None:
    sections = [
        _sec(0, "Lead story", "hero"),
        _sec(1, "AI Twitter Recap", "boundary-and-recap-body"),
    ]
    split = split_ainews_sections(sections)
    assert split.recap_sections[0].heading == "AI Twitter Recap"
    assert split.recap_sections[0].text == "boundary-and-recap-body"
    assert "AI Twitter Recap" not in [s.heading for s in split.hero_sections]


def test_reve_2_and_ideogram_4_layouts_is_not_boundary() -> None:
    assert not is_recap_boundary_heading("Reve 2 and Ideogram 4 Layouts")
    sections = [_sec(0, "Reve 2 and Ideogram 4 Layouts", "content")]
    split = split_ainews_sections(sections)
    assert split.has_boundary is False
    assert len(split.hero_sections) == 1
    assert len(split.recap_sections) == 0


def test_empty_heading_is_not_boundary() -> None:
    assert not is_recap_boundary_heading(None)
    assert not is_recap_boundary_heading("")
    assert not is_recap_boundary_heading("   ")
    sections = [
        _sec(0, None, "preamble"),
        _sec(1, "AI Twitter Recap", "recap"),
    ]
    split = split_ainews_sections(sections)
    assert split.boundary_heading == "AI Twitter Recap"
    assert split.hero_sections[0].heading is None


def test_no_boundary_puts_all_sections_in_hero_full_issue() -> None:
    sections = [
        _sec(0, "Microsoft Build: MAI models", "mai"),
        _sec(1, "Other notable updates", "more"),
    ]
    split = split_ainews_sections(sections)
    assert split.has_boundary is False
    assert split.boundary_heading is None
    assert len(split.hero_sections) == 2
    assert len(split.recap_sections) == 0
    assert {s.section_id for s in split.hero_sections} == {"s0", "s1"}


def test_only_first_boundary_is_used() -> None:
    sections = [
        _sec(0, "Hero A", "a"),
        _sec(1, "Quick Hits", "first-boundary"),
        _sec(2, "Hero-looking but after boundary", "should-be-recap"),
        _sec(3, "AI Reddit Recap", "still-recap"),
    ]
    split = split_ainews_sections(sections)
    assert split.boundary_heading == "Quick Hits"
    assert [s.heading for s in split.hero_sections] == ["Hero A"]
    assert [s.heading for s in split.recap_sections] == [
        "Quick Hits",
        "Hero-looking but after boundary",
        "AI Reddit Recap",
    ]


def test_weekly_recap_short_heading_is_boundary() -> None:
    assert is_recap_boundary_heading("weekly recap")
    split = split_ainews_sections([_sec(0, "Intro", "i"), _sec(1, "weekly recap", "w")])
    assert split.has_boundary is True
    assert split.boundary_heading == "weekly recap"


def test_long_title_ending_with_recap_over_40_chars_is_not_boundary() -> None:
    # len("x" * 35 + " recap") == 41 > 40
    long_heading = ("x" * 35) + " recap"
    assert len(long_heading) > 40
    assert long_heading.endswith(" recap")
    assert not is_recap_boundary_heading(long_heading)

    sections = [
        _sec(0, "Hero", "hero"),
        _sec(1, long_heading, "not-a-boundary"),
        _sec(2, "AI Twitter Recap", "real-boundary"),
    ]
    split = split_ainews_sections(sections)
    assert split.boundary_heading == "AI Twitter Recap"
    assert len(split.hero_sections) == 2
    assert split.hero_sections[1].heading == long_heading
    assert split.recap_sections[0].heading == "AI Twitter Recap"
