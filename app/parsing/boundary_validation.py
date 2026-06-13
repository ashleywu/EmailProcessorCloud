"""Validation and hashing utilities for the Phase 7 boundary classifier."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence

from app.models.content_units import BoundaryLLMOutput, BoundaryOutlineSection
from app.models.section import EmailSection
from app.parsing.content_unit_grouping import is_hard_boundary_section


def validate_boundary_llm_output(
    llm_output: BoundaryLLMOutput,
    *,
    run_section_keys: list[str],
    all_sections: Sequence[EmailSection],
    is_hard_boundary: Callable[[EmailSection], bool] = is_hard_boundary_section,
) -> list[str]:
    """Validate LLM boundary output for one non-promo run against raw section order.

    Checks are performed against *all_sections* reading order (not a flattened
    non-promo outline).  *run_section_keys* lists the section keys belonging to
    the current contiguous non-promo run.

    Rules:
    1. No invented keys — keys must belong to the run.
    2. No missing keys — every run key must appear exactly once.
    3. No duplicate keys.
    4. Each unit's keys must be contiguous in raw order.
    5. No unit may span across a hard-boundary (promo) section.
    6. Unit intervals strictly increasing (no overlap).
    """
    errors: list[str] = []

    valid_run_keys: set[str] = set(run_section_keys)
    key_index: dict[str, int] = {s.section_id.strip(): i for i, s in enumerate(all_sections)}

    seen: dict[str, str] = {}
    unit_intervals: list[tuple[int, int, str]] = []

    for unit in llm_output.units:
        if not unit.section_keys:
            errors.append(f"empty_section_keys in unit: {unit.unit_title!r}")
            continue

        indices: list[int] = []
        for key in unit.section_keys:
            if key not in valid_run_keys:
                if key in key_index:
                    errors.append(
                        f"section_key_outside_run: {key!r} in unit {unit.unit_title!r}",
                    )
                else:
                    errors.append(f"invented_section_key: {key!r} in unit {unit.unit_title!r}")
                continue
            if key in seen:
                errors.append(
                    f"duplicate_section_key: {key!r} appears in both"
                    f" {seen[key]!r} and {unit.unit_title!r}",
                )
            else:
                seen[key] = unit.unit_title
                indices.append(key_index[key])

        if not indices:
            continue

        sorted_idx = sorted(indices)
        expected = list(range(sorted_idx[0], sorted_idx[-1] + 1))
        if sorted_idx != expected:
            errors.append(
                f"non_contiguous_in_raw_order in unit {unit.unit_title!r}:"
                f" {unit.section_keys} (raw positions {sorted_idx})",
            )
            continue

        lo, hi = sorted_idx[0], sorted_idx[-1]
        for i in range(lo, hi + 1):
            sec = all_sections[i]
            sid = sec.section_id.strip()
            if sid not in unit.section_keys and is_hard_boundary(sec):
                errors.append(
                    f"spans_hard_boundary: unit {unit.unit_title!r} crosses"
                    f" hard boundary section {sid!r}",
                )
                break

        unit_intervals.append((sorted_idx[0], sorted_idx[-1], unit.unit_title))

    for key in run_section_keys:
        if key not in seen:
            errors.append(f"missing_section_key: {key!r} not covered by any unit")

    sorted_intervals = sorted(unit_intervals, key=lambda t: t[0])
    prev_end = -1
    for start, end, title in sorted_intervals:
        if start <= prev_end:
            errors.append(
                f"overlapping_units: unit {title!r} starts at position {start}"
                f" which overlaps previous interval ending at {prev_end}",
            )
        prev_end = end

    return errors


def compute_outline_hash(sections: list[BoundaryOutlineSection]) -> str:
    """Stable 16-char SHA-256 prefix of the structural outline sent to the LLM.

    Includes ``snippet_len`` so budget-driven snippet truncation changes the hash.
    Call **after** final budget shaping, immediately before the LLM request.
    """
    stable = [
        {
            "section_key": s.section_key,
            "heading": s.heading,
            "char_count": s.char_count,
            "snippet_len": len(s.snippet),
        }
        for s in sections
    ]
    blob = json.dumps(stable, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def compute_composite_outline_hash(hashes: list[str]) -> str:
    """Combine per-run outline hashes into one email-level hash."""
    if not hashes:
        return compute_outline_hash([])
    if len(hashes) == 1:
        return hashes[0]
    blob = "|".join(hashes)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


__all__ = [
    "compute_composite_outline_hash",
    "compute_outline_hash",
    "validate_boundary_llm_output",
]
