"""Normalize and merge newsletter sections before per-section routing (Step 3).

Caps and merge policy align with ingest budget: bounded LLM slices without silently
truncating unconsumed prose—prefer merging adjacent sections toward ``MAX_SECTIONS_PER_EMAIL``.
"""

from __future__ import annotations

import hashlib
import json

from app.models.section import EmailSection
from app.parsing.parser import ParsedHtmlResult

MAX_SECTIONS_PER_EMAIL = 8
MIN_SECTION_CHARS = 300
MAX_SECTION_CHARS = 8000
# When the raw DOM slice count explodes into micro-sections, fall back to a single envelope slice.
PATHOLOGICAL_RAW_SECTION_THRESHOLD = 48


def truncate_section_text(text: str, *, max_chars: int = MAX_SECTION_CHARS) -> str:
    t = str(text).strip()
    if len(t) <= max_chars:
        return t
    return f"{t[: max_chars - 1]}…"


def compute_section_content_hash(sec: EmailSection) -> str:
    """Stable hash over normalized section body + authoritative links (ordering preserved)."""

    payload = {
        "text": truncate_section_text(sec.text, max_chars=MAX_SECTION_CHARS),
        "links": list(sec.links),
    }
    canon = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _merge_two(left: EmailSection, right: EmailSection) -> EmailSection:
    t1 = truncate_section_text(left.text, max_chars=MAX_SECTION_CHARS)
    t2 = truncate_section_text(right.text, max_chars=MAX_SECTION_CHARS)
    merged_raw = "\n\n".join(p for p in (t1, t2) if p)
    merged_text = truncate_section_text(merged_raw, max_chars=MAX_SECTION_CHARS)

    links: list[str] = []
    seen: set[str] = set()
    for lst in (left.links, right.links):
        for u in lst:
            if u not in seen:
                seen.add(u)
                links.append(u)

    images: list[str] = []
    seen_i: set[str] = set()
    for lst in (left.image_urls, right.image_urls):
        for im in lst:
            if im not in seen_i:
                seen_i.add(im)
                images.append(im)

    heading = left.heading if left.heading else right.heading

    return EmailSection(
        section_id=left.section_id,
        order_index=min(left.order_index, right.order_index),
        heading=heading,
        text=merged_text,
        links=links,
        image_urls=images,
        email_id=left.email_id,
    )


def _renumber_sections(sections: list[EmailSection]) -> list[EmailSection]:
    out: list[EmailSection] = []
    for i, s in enumerate(sections):
        kwargs = dict(s.model_dump())
        kwargs["section_id"] = f"s{i}"
        kwargs["order_index"] = i
        out.append(EmailSection(**kwargs))
    return out


def _single_fallback_from_parsed(parsed: ParsedHtmlResult) -> EmailSection:
    blob = truncate_section_text(parsed.plain_text, max_chars=MAX_SECTION_CHARS)
    return EmailSection(
        section_id="s0",
        order_index=0,
        heading=None,
        text=blob,
        links=list(parsed.links),
        image_urls=list(parsed.image_urls),
    )


def normalize_sections_for_routing(parsed: ParsedHtmlResult) -> list[EmailSection]:
    """Merge / truncate slices so downstream routing respects caps.

    Prefer merging adjacent small sections toward ``<= MAX_SECTIONS_PER_EMAIL``.
    Fallback to exactly one envelope section only when the raw slice count looks pathological.
    """

    raw = list(parsed.sections)
    if not raw:
        return [_single_fallback_from_parsed(parsed)]

    raw_count = len(raw)
    secs = [
        EmailSection(
            section_id=s.section_id,
            order_index=s.order_index,
            heading=s.heading,
            text=truncate_section_text(s.text),
            links=list(s.links),
            image_urls=list(s.image_urls),
            email_id=s.email_id,
        )
        for s in raw
    ]

    if raw_count >= PATHOLOGICAL_RAW_SECTION_THRESHOLD:
        return _renumber_sections(
            [_single_fallback_from_parsed(parsed)],
        )

    # Reduce cardinality first (budget), then inflate tiny neighbors.
    while len(secs) > MAX_SECTIONS_PER_EMAIL:
        best_i = 0
        best_score: int | None = None
        for i in range(len(secs) - 1):
            score = len(secs[i].text) + len(secs[i + 1].text)
            if best_score is None or score < best_score:
                best_score = score
                best_i = i
        merged = _merge_two(secs[best_i], secs[best_i + 1])
        secs = [*secs[:best_i], merged, *secs[best_i + 2 :]]

    def _inflate_short_sections() -> bool:
        if len(secs) <= 1:
            return False
        idxs = [i for i, s in enumerate(secs) if len(s.text) < MIN_SECTION_CHARS]
        if not idxs:
            return False
        i = idxs[0]
        merge_left = i > 0 and (
            i + 1 >= len(secs) or len(secs[i - 1].text) <= len(secs[i + 1].text)
        )
        if merge_left and i > 0:
            merged = _merge_two(secs[i - 1], secs[i])
            secs[:] = [*secs[: i - 1], merged, *secs[i + 1 :]]
        elif i + 1 < len(secs):
            merged = _merge_two(secs[i], secs[i + 1])
            secs[:] = [*secs[:i], merged, *secs[i + 2 :]]
        else:
            merged = _merge_two(secs[i - 1], secs[i])
            secs[:] = [*secs[: i - 1], merged]
        return True

    guard = 4096  # merges are finite; bounded loop avoids pathological churn
    while guard > 0 and any(len(s.text) < MIN_SECTION_CHARS for s in secs) and len(secs) > 1:
        guard -= 1
        changed = _inflate_short_sections()
        if not changed:
            break
        while len(secs) > MAX_SECTIONS_PER_EMAIL:
            best_i = 0
            best_score_m: int | None = None
            for i in range(len(secs) - 1):
                score_m = len(secs[i].text) + len(secs[i + 1].text)
                if best_score_m is None or score_m < best_score_m:
                    best_score_m = score_m
                    best_i = i
            merged_m = _merge_two(secs[best_i], secs[best_i + 1])
            secs = [*secs[:best_i], merged_m, *secs[best_i + 2 :]]

    while len(secs) > MAX_SECTIONS_PER_EMAIL:
        merged_tail = _merge_two(secs[-2], secs[-1])
        secs = [*secs[:-2], merged_tail]

    return _renumber_sections(secs)
