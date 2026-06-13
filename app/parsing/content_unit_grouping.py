"""Deterministic content-unit grouping for the generic content-unit pipeline (Phase 5–7).

Uses keyword-based promo hard boundaries until interrupt detection (P1a) replaces
``is_promo_section()`` in a later milestone.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.models.content_units import ContentUnit, GroupingAmbiguityReason, GroupingResult
from app.models.section import EmailSection

_LONG_FORM_CHAR_THRESHOLD = 1800
_GRAY_ZONE_MIN_SECTIONS = 3
_GRAY_ZONE_MAX_SECTIONS = 8
_MULTI_URL_SPLIT_THRESHOLD = 3
_NUMBERED_CHAPTER_RE = re.compile(r"^\s*\d+\.\s+")

_PROMO_KEYWORDS: tuple[str, ...] = (
    "register",
    "enroll",
    "cohort",
    "webinar",
    "workshop",
    "masterclass",
    "bootcamp",
    "rsvp",
    "limited seats",
    "apply now",
    "tickets",
    "early bird",
    "join us",
    "sign up",
    "sponsor",
)


def is_promo_section(section: EmailSection) -> bool:
    """Return True when a section looks like promotional / enrollment content."""

    text = " ".join(part for part in (section.heading, section.text) if part).lower()
    return sum(1 for kw in _PROMO_KEYWORDS if kw in text) >= 2


def is_hard_boundary_section(section: EmailSection) -> bool:
    """Promo sections are hard boundaries in the Phase 7 generic path."""

    return is_promo_section(section)


def split_non_promo_runs(sections: Sequence[EmailSection]) -> list[list[EmailSection]]:
    """Split *sections* into contiguous non-promo runs separated by promo hard boundaries."""

    runs: list[list[EmailSection]] = []
    current: list[EmailSection] = []
    for section in sections:
        if is_promo_section(section):
            if current:
                runs.append(current)
                current = []
            continue
        current.append(section)
    if current:
        runs.append(current)
    return runs


def _section_char_count(section: EmailSection) -> int:
    return len(section.text or "")


def _extract_https_links(sections: Sequence[EmailSection]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for section in sections:
        for link in section.links:
            url = str(link).strip()
            if url.startswith("https://") and url not in seen:
                seen.add(url)
                out.append(url)
    return out


def _has_numbered_chapter_signal(sections: Sequence[EmailSection]) -> bool:
    count = sum(
        1
        for section in sections
        if section.heading and _NUMBERED_CHAPTER_RE.match(section.heading.strip())
    )
    return count >= 2


def _looks_like_single_long_form(sections: Sequence[EmailSection]) -> bool:
    if not sections or len(sections) > _GRAY_ZONE_MAX_SECTIONS:
        return False
    total_chars = sum(_section_char_count(section) for section in sections)
    if total_chars < _LONG_FORM_CHAR_THRESHOLD:
        return False
    return len(_extract_https_links(sections)) <= 1


def _has_mixed_heading_pattern(sections: Sequence[EmailSection]) -> bool:
    substantive = [
        section.heading.strip()
        for section in sections
        if section.heading and len(section.heading.strip()) > 3
    ]
    if len(substantive) < 3:
        return False
    if _has_numbered_chapter_signal(sections):
        return False
    return len(set(substantive)) >= 3


def _is_ambiguous(
    non_promo_sections: Sequence[EmailSection],
) -> tuple[bool, list[GroupingAmbiguityReason]]:
    reasons: list[GroupingAmbiguityReason] = []
    count = len(non_promo_sections)
    if count <= 1:
        return False, reasons
    if _has_numbered_chapter_signal(non_promo_sections):
        return False, reasons

    url_count = len(_extract_https_links(non_promo_sections))
    if url_count >= _MULTI_URL_SPLIT_THRESHOLD:
        return False, reasons
    if _looks_like_single_long_form(non_promo_sections):
        return False, reasons

    if _GRAY_ZONE_MIN_SECTIONS <= count <= _GRAY_ZONE_MAX_SECTIONS:
        reasons.append(GroupingAmbiguityReason.SECTION_COUNT_GRAY_ZONE)
        if _has_mixed_heading_pattern(non_promo_sections):
            reasons.append(GroupingAmbiguityReason.MIXED_HEADING_PATTERN)
        if 1 <= url_count <= 2:
            reasons.append(GroupingAmbiguityReason.AMBIGUOUS_URL_COUNT)
        return True, reasons

    return False, reasons


def _deterministic_non_promo_groups(sections: Sequence[EmailSection]) -> list[list[EmailSection]]:
    non_promo = [section for section in sections if not is_promo_section(section)]
    if len(_extract_https_links(non_promo)) >= _MULTI_URL_SPLIT_THRESHOLD:
        return [[section] for section in non_promo]
    return split_non_promo_runs(sections)


def build_content_units_from_section_groups(
    groups: Sequence[Sequence[EmailSection]],
) -> list[ContentUnit]:
    units: list[ContentUnit] = []
    for index, group in enumerate(groups):
        headings = [section.heading for section in group if section.heading]
        texts = [section.text for section in group if (section.text or "").strip()]
        links: list[str] = []
        seen: set[str] = set()
        for section in group:
            for link in section.links:
                url = str(link).strip()
                if url.startswith("https://") and url not in seen:
                    seen.add(url)
                    links.append(url)
        units.append(
            ContentUnit(
                content_unit_key=f"u{index}",
                unit_text="\n\n".join(texts),
                headings=headings,
                links=links,
                section_keys=[section.section_id.strip() for section in group],
            ),
        )
    return units


def validate_groups_respect_hard_boundaries(
    groups: Sequence[Sequence[EmailSection]],
    all_sections: Sequence[EmailSection],
) -> list[str]:
    errors: list[str] = []
    key_index = {section.section_id.strip(): idx for idx, section in enumerate(all_sections)}

    for group in groups:
        if len(group) <= 1:
            continue
        indices = sorted(key_index[section.section_id.strip()] for section in group)
        group_keys = {section.section_id.strip() for section in group}
        for idx in range(indices[0], indices[-1] + 1):
            section = all_sections[idx]
            sid = section.section_id.strip()
            if sid in group_keys:
                continue
            if is_hard_boundary_section(section):
                errors.append(f"spans_hard_boundary: group crosses hard boundary section {sid!r}")
            else:
                errors.append(f"non_contiguous_group: group skips section {sid!r}")
    return errors


def validate_run_groups_coverage(
    groups: Sequence[Sequence[EmailSection]],
    run_section_keys: Sequence[str],
) -> list[str]:
    errors: list[str] = []
    seen: dict[str, int] = {}
    for group in groups:
        for section in group:
            sid = section.section_id.strip()
            seen[sid] = seen.get(sid, 0) + 1
    for sid, count in seen.items():
        if count > 1:
            errors.append(f"duplicate_section_key: {sid!r} appears {count} times")
    for key in run_section_keys:
        if key not in seen:
            errors.append(f"missing_section_key: {key!r} not covered by any group")
    return errors


def assemble_final_groups(
    all_sections: Sequence[EmailSection],
    non_promo_groups: Sequence[Sequence[EmailSection]],
) -> list[list[EmailSection]]:
    boundary_errors = validate_groups_respect_hard_boundaries(non_promo_groups, all_sections)
    if boundary_errors:
        msg = "assemble_final_groups: " + "; ".join(boundary_errors)
        raise ValueError(msg)

    group_index_by_key: dict[str, int] = {}
    for group_idx, group in enumerate(non_promo_groups):
        for section in group:
            group_index_by_key[section.section_id.strip()] = group_idx

    assembled: list[list[EmailSection]] = []
    current_group_idx: int | None = None
    current: list[EmailSection] = []

    for section in all_sections:
        sid = section.section_id.strip()
        if is_promo_section(section):
            if current:
                assembled.append(current)
                current = []
                current_group_idx = None
            assembled.append([section])
            continue

        group_idx = group_index_by_key.get(sid)
        if group_idx is None:
            msg = f"assemble_final_groups: section {sid!r} missing from non_promo_groups"
            raise ValueError(msg)

        if current_group_idx is None or group_idx != current_group_idx:
            if current:
                assembled.append(current)
            current = [section]
            current_group_idx = group_idx
        else:
            current.append(section)

    if current:
        assembled.append(current)
    return assembled


def conservative_non_promo_groups(sections: Sequence[EmailSection]) -> list[list[EmailSection]]:
    return [[section] for section in sections if not is_promo_section(section)]


def conservative_groups_for_run(
    all_sections: Sequence[EmailSection],
    run_section_keys: Sequence[str],
) -> list[list[EmailSection]]:
    key_set = set(run_section_keys)
    return [[section] for section in all_sections if section.section_id.strip() in key_set]


def build_canonical_units(
    sections: Sequence[EmailSection],
    non_promo_groups: Sequence[Sequence[EmailSection]],
) -> list[ContentUnit]:
    return build_content_units_from_section_groups(assemble_final_groups(sections, non_promo_groups))


def deterministic_units_for_run(
    deterministic_units: Sequence[ContentUnit],
    run_section_keys: Sequence[str],
) -> list[ContentUnit]:
    key_set = set(run_section_keys)
    scoped: list[ContentUnit] = []
    for unit in deterministic_units:
        if not unit.section_keys:
            continue
        if any(key not in key_set for key in unit.section_keys):
            continue
        if any(key in key_set for key in unit.section_keys):
            scoped.append(unit)
    return scoped


def group_content_units(sections: Sequence[EmailSection]) -> GroupingResult:
    ordered = list(sections)
    conservative_groups = [[section] for section in ordered]
    conservative_units = build_content_units_from_section_groups(conservative_groups)

    non_promo = [section for section in ordered if not is_promo_section(section)]
    ambiguous, ambiguity_reasons = _is_ambiguous(non_promo)

    non_promo_groups = _deterministic_non_promo_groups(ordered)
    final_groups = assemble_final_groups(ordered, non_promo_groups)
    units = build_content_units_from_section_groups(final_groups)

    return GroupingResult(
        units=units,
        conservative_units=conservative_units,
        ambiguous=ambiguous,
        ambiguity_reasons=ambiguity_reasons,
        non_promo_section_count=len(non_promo),
    )


__all__ = [
    "assemble_final_groups",
    "build_canonical_units",
    "build_content_units_from_section_groups",
    "conservative_groups_for_run",
    "conservative_non_promo_groups",
    "deterministic_units_for_run",
    "group_content_units",
    "is_hard_boundary_section",
    "is_promo_section",
    "split_non_promo_runs",
    "validate_groups_respect_hard_boundaries",
    "validate_run_groups_coverage",
]
