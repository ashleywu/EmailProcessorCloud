from __future__ import annotations

from pathlib import Path

from app.parsing.parser import ParsedHtmlResult

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Canonical prompt stems for ``DailyDigestAgent`` section-scoped completions (``{stem}.md``).
SECTION_PIPELINE_PROMPT_STEMS: tuple[str, ...] = (
    "router",
    "technology_section",
    "leadership_section",
    "radar",
    "courses",
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
