"""Detect hero vs recap boundaries in AINews (Latent Space) issue section lists."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.models.section import EmailSection
from app.parsing.map_reduce_chunks import format_sections_plaintext

# Substrings matched against normalized heading text (lowercase, collapsed whitespace).
_RECAP_BOUNDARY_SUBSTRINGS: tuple[str, ...] = (
    "ai twitter recap",
    "ai reddit recap",
    "ai discord recap",
    "quick hits",
)

# Headings that are recap boundaries when equal or when the heading is essentially this label.
_RECAP_BOUNDARY_EXACT: frozenset[str] = frozenset(
    {
        "recap",
        "links",
        "ai news recap",
    },
)

_RECAP_SUFFIX_RE = re.compile(
    r"^(ai\s+)?(twitter|reddit|discord)\s+recap$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AINewsSectionSplit:
    """Sections partitioned at the first recap-style heading (if any)."""

    hero_sections: tuple[EmailSection, ...]
    recap_sections: tuple[EmailSection, ...]
    boundary_heading: str | None
    has_boundary: bool


def normalize_heading(heading: str | None) -> str:
    return " ".join(str(heading or "").lower().split())


def is_recap_boundary_heading(heading: str | None) -> bool:
    """True when a section heading starts the recap portion of an AINews issue."""

    h = normalize_heading(heading)
    if not h:
        return False
    if h in _RECAP_BOUNDARY_EXACT:
        return True
    if any(marker in h for marker in _RECAP_BOUNDARY_SUBSTRINGS):
        return True
    if _RECAP_SUFFIX_RE.match(h):
        return True
    # e.g. "weekly recap", "community recap" — short headings ending in " recap"
    if h.endswith(" recap") and len(h) <= 40:
        return True
    return False


def split_ainews_sections(sections: Sequence[EmailSection]) -> AINewsSectionSplit:
    """Split ordered sections into hero (pre-boundary) and recap (boundary onward)."""

    ordered = tuple(sorted(sections, key=lambda s: s.order_index))
    if not ordered:
        return AINewsSectionSplit(
            hero_sections=(),
            recap_sections=(),
            boundary_heading=None,
            has_boundary=False,
        )

    boundary_index: int | None = None
    boundary_heading: str | None = None
    for i, sec in enumerate(ordered):
        if is_recap_boundary_heading(sec.heading):
            boundary_index = i
            boundary_heading = sec.heading
            break

    if boundary_index is None:
        return AINewsSectionSplit(
            hero_sections=ordered,
            recap_sections=(),
            boundary_heading=None,
            has_boundary=False,
        )

    hero = ordered[:boundary_index]
    recap = ordered[boundary_index:]
    return AINewsSectionSplit(
        hero_sections=hero,
        recap_sections=recap,
        boundary_heading=boundary_heading,
        has_boundary=True,
    )


def format_sections_for_llm(sections: Sequence[EmailSection]) -> str:
    """Plaintext block for hero/recap LLM calls (same delimiter style as map chunks)."""

    return format_sections_plaintext(sections)
