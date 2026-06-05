"""Pack parsed newsletter sections into bounded map-phase chunks (no LLM)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.models.section import EmailSection

_NO_HEADING = "(no heading)"
_SECTION_SEP = "\n\n---\n\n"


@dataclass(frozen=True, slots=True)
class MapReduceChunk:
    section_ids: tuple[str, ...]
    headings: tuple[str | None, ...]
    text: str


def _format_section_block(section: EmailSection) -> str:
    heading = section.heading
    label = heading.strip() if heading and str(heading).strip() else _NO_HEADING
    body = str(section.text).strip()
    return f"## {label}\n\n{body}"


def _chunk_char_len(section: EmailSection) -> int:
    return len(_format_section_block(section))


def _join_chunk_text(sections: Sequence[EmailSection]) -> str:
    return _SECTION_SEP.join(_format_section_block(s) for s in sections)


def format_sections_plaintext(sections: Sequence[EmailSection]) -> str:
    """Format sections with headings for hero/recap or map chunk bodies."""

    ordered = sorted(sections, key=lambda s: s.order_index)
    if not ordered:
        return ""
    return _join_chunk_text(ordered)


def _sections_from_chunk(sections: Sequence[EmailSection]) -> MapReduceChunk:
    return MapReduceChunk(
        section_ids=tuple(s.section_id for s in sections),
        headings=tuple(s.heading for s in sections),
        text=_join_chunk_text(sections),
    )


def _merge_adjacent_pair(
    chunks: list[list[EmailSection]],
    index: int,
) -> None:
    merged_secs = [*chunks[index], *chunks[index + 1]]
    chunks[index : index + 2] = [merged_secs]


def chunk_sections_for_map(
    sections: Sequence[EmailSection],
    *,
    target_chars: int,
    max_chunks: int,
) -> list[MapReduceChunk]:
    """Greedy pack by order_index; cap chunk count by merging smallest adjacent pairs."""

    if target_chars < 1:
        raise ValueError("target_chars must be >= 1")
    if max_chunks < 1:
        raise ValueError("max_chunks must be >= 1")

    ordered = sorted(sections, key=lambda s: s.order_index)
    if not ordered:
        fallback = EmailSection(section_id="s0", order_index=0, text="")
        return [_sections_from_chunk([fallback])]

    groups: list[list[EmailSection]] = []
    current: list[EmailSection] = []

    for sec in ordered:
        sec_len = _chunk_char_len(sec)
        if sec_len > target_chars:
            if current:
                groups.append(current)
                current = []
            groups.append([sec])
            continue

        if not current:
            current = [sec]
            continue

        trial = [*current, sec]
        if len(_join_chunk_text(trial)) <= target_chars:
            current = trial
        else:
            groups.append(current)
            current = [sec]

    if current:
        groups.append(current)

    while len(groups) > max_chunks:
        best_i = 0
        best_size: int | None = None
        for i in range(len(groups) - 1):
            size = sum(_chunk_char_len(s) for s in groups[i]) + sum(
                _chunk_char_len(s) for s in groups[i + 1]
            )
            if best_size is None or size < best_size:
                best_size = size
                best_i = i
        _merge_adjacent_pair(groups, best_i)

    return [_sections_from_chunk(g) for g in groups]
