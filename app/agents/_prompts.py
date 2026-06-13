from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app.parsing.parser import ParsedHtmlResult

if TYPE_CHECKING:
    from app.models.content_units import (
        BoundaryOutlineSection,
        ContentUnit,
        GroupingAmbiguityReason,
    )

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Canonical prompt stems for ``DailyDigestAgent`` section-scoped completions (``{stem}.md``).
SECTION_PIPELINE_PROMPT_STEMS: tuple[str, ...] = (
    "router",
    "technology_section",
    "leadership_section",
    "radar",
    "courses",
)

CONTENT_UNIT_PROMPT_STEMS: tuple[str, ...] = (
    "boundary_classifier",
    "content_unit_classifier",
    "content_unit_radar",
    "content_unit_technology",
    "content_unit_leadership",
    "content_unit_courses",
    "leadership_essay",
    "technical_longform",
)

# Deprecated whole-email prompts retained under ``prompts/*.md`` — not referenced by agents.
LEGACY_EMAIL_LEVEL_PROMPT_STEMS: tuple[str, ...] = (
    "technology",
    "leadership",
)


def load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def format_router_section_input(
    *,
    subject: str | None,
    section_heading: str | None,
    plain_text: str,
) -> str:
    """User message body for RouterAgent (one DOM slice per call)."""

    blocks: list[str] = []
    if subject is not None and str(subject).strip():
        blocks.append(f"Email subject (optional): {str(subject).strip()}")
    if section_heading is not None and str(section_heading).strip():
        blocks.append(f"Section heading: {str(section_heading).strip()}")
    blocks.append(f"Section plain text (this slice only):\n{plain_text}")
    return "\n\n".join(blocks)


def format_content_unit_classifier_input(
    *,
    subject: str | None,
    unit_title: str | None,
    headings: list[str],
    plain_text: str,
    links: list[str],
) -> str:
    """User message body for ContentUnitClassifierAgent (one grouped unit)."""

    blocks: list[str] = []
    if subject is not None and str(subject).strip():
        blocks.append(f"Email subject (optional): {str(subject).strip()}")
    if unit_title is not None and str(unit_title).strip():
        blocks.append(f"Content unit title: {str(unit_title).strip()}")
    if headings:
        blocks.append("Section headings in this unit:\n" + "\n".join(f"- {h}" for h in headings if h))
    uniq: list[str] = []
    seen: set[str] = set()
    for link in links:
        s = str(link).strip()
        if s.startswith("https://") and s not in seen:
            seen.add(s)
            uniq.append(s)
    numbered = "\n".join(f"  {i}. {url}" for i, url in enumerate(uniq, start=1))
    blocks.append("Candidate HTTPS links:\n" + (numbered if numbered else "  (none)"))
    blocks.append(f"Content unit plain text:\n{plain_text}")
    return "\n\n".join(blocks)


def format_processor_section_plain(
    *,
    subject: str | None,
    section_heading: str | None,
    plain_text: str,
) -> str:
    """Subject + slice body for processors without URL candidate blocks."""

    blocks: list[str] = []
    if subject is not None and str(subject).strip():
        blocks.append(f"Subject: {str(subject).strip()}")
    if section_heading is not None and str(section_heading).strip():
        blocks.append(f"Section heading: {str(section_heading).strip()}")
    blocks.append(f"Section plain text (this slice only):\n{plain_text}")
    return "\n\n".join(blocks)


def format_newsletter_text(*, subject: str | None, plain_text: str) -> str:
    blocks: list[str] = []
    if subject:
        blocks.append(f"Subject: {subject}")
    blocks.append("Plain text:\n" + plain_text)
    return "\n\n".join(blocks)


def format_section_https_candidates(
    *,
    subject: str | None,
    section_plain_text: str,
    heading: str | None = None,
    section_links: list[str],
    original_url_hint: str | None,
    link_list_title: str,
) -> str:
    blocks: list[str] = []
    if subject:
        blocks.append(f"Subject: {subject}")
    if heading:
        blocks.append(f"Section heading: {heading}")

    uniq: list[str] = []
    seen: set[str] = set()
    for u in section_links:
        s = str(u).strip()
        if s.startswith("https://") and s not in seen:
            seen.add(s)
            uniq.append(s)

    oz = ""
    if isinstance(original_url_hint, str):
        oz = original_url_hint.strip()
    if oz.startswith("https://") and oz not in seen:
        uniq.insert(0, oz)
        seen.add(oz)

    numbered = "\n".join(f"  {i}. {url}" for i, url in enumerate(uniq, start=1))
    blocks.append(link_list_title + "\n" + numbered if numbered else link_list_title + "\n  (none)")
    blocks.append(f"Section plain text (this slice only):\n" + section_plain_text)
    return "\n\n".join(blocks)


def format_boundary_classifier_input(
    *,
    sender: str | None,
    subject: str | None,
    original_url: str | None,
    sections: list[BoundaryOutlineSection],
    deterministic_units: list[ContentUnit],
    ambiguity_reasons: list[GroupingAmbiguityReason],
    hard_boundary_section_keys: list[str] | None = None,
) -> str:
    """User message for BoundaryClassifierAgent — structural outline only, no full content."""

    blocks: list[str] = []

    # --- Metadata ---
    meta: list[str] = []
    if sender:
        meta.append(f"Sender: {sender.strip()}")
    if subject:
        meta.append(f"Subject: {subject.strip()}")
    if original_url and str(original_url).startswith("https://"):
        meta.append(f"Original URL: {original_url.strip()}")
    if hard_boundary_section_keys:
        keys_str = ", ".join(hard_boundary_section_keys)
        meta.append(f"Hard boundary sections (do not merge across): {keys_str}")
    if meta:
        blocks.append("Email metadata:\n" + "\n".join(f"- {m}" for m in meta))

    # --- Structural outline ---
    outline_lines: list[str] = [f"Structural outline ({len(sections)} sections):"]
    for i, sec in enumerate(sections, start=1):
        heading_str = f"{sec.heading!r}" if sec.heading else "(no heading)"
        outline_lines.append(
            f"{i}. [{sec.section_key}] {heading_str}"
            f" — {sec.char_count} chars, {sec.link_count} links"
        )
        if sec.primary_links:
            link_str = ", ".join(sec.primary_links[:3])
            outline_lines.append(f"   Links: {link_str}")
        if sec.snippet:
            outline_lines.append(f"   Snippet: {sec.snippet!r}")
    blocks.append("\n".join(outline_lines))

    # --- Deterministic guess ---
    if deterministic_units:
        guess_lines: list[str] = ["Deterministic grouping guess:"]
        for u in deterministic_units:
            guess_lines.append(f"  - unit {u.content_unit_key}: sections {u.section_keys}")
        blocks.append("\n".join(guess_lines))

    # --- Ambiguity reasons ---
    if ambiguity_reasons:
        reasons_str = ", ".join(str(r) for r in ambiguity_reasons)
        blocks.append(f"Ambiguity reasons: {reasons_str}")

    return "\n\n".join(blocks)


def format_subject_plain_https_link_candidates(
    *,
    subject: str | None,
    parsed: ParsedHtmlResult,
    link_list_title: str,
) -> str:
    blocks: list[str] = []
    if subject:
        blocks.append(f"Subject: {subject}")
    original_raw = parsed.original_url
    original = original_raw.strip() if isinstance(original_raw, str) else ""
    if original.startswith("https://"):
        blocks.append(f"Original URL (hint): {original}")

    uniq: list[str] = []
    seen: set[str] = set()

    candidates = list(parsed.links)
    if original.startswith("https://") and original not in candidates:
        candidates = [original, *candidates]

    for u in candidates:
        s = str(u).strip()
        if s.startswith("https://") and s not in seen:
            seen.add(s)
            uniq.append(s)

    numbered = "\n".join(f"  {i}. {url}" for i, url in enumerate(uniq, start=1))
    blocks.append(link_list_title + "\n" + numbered if numbered else link_list_title + "\n  (none)")
    blocks.append("Plain text:\n" + parsed.plain_text)
    return "\n\n".join(blocks)
