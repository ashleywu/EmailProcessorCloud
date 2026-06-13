"""Profile fast-path grouping and structural counter-evidence (V1)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.models.content_units import ContentUnit
from app.models.section import EmailSection
from app.parsing.interrupt_detection import (
    InterruptRole,
    detect_interrupt_roles,
    is_article_body_section,
    is_strippable_interrupt,
)
from app.parsing.parser import ParsedHtmlResult
from app.processing.sender_profiles import (
    ARTICLE_BODY_MIN_CHARS,
    PROMO_DOMINATED_RATIO,
    GroupingStrategy,
    SenderProfile,
)


@dataclass(frozen=True, slots=True)
class ProfileRunPlan:
    profile: SenderProfile
    article_unit: ContentUnit
    hidden_section_keys: tuple[str, ...]
    interrupt_roles: tuple[InterruptRole, ...]


def group_profile_units(
    profile: SenderProfile,
    sections: list[EmailSection],
    *,
    roles: list[InterruptRole] | None = None,
) -> ProfileRunPlan:
    """Apply profile merge strategy after shared interrupt detection."""

    resolved_roles = roles if roles is not None else detect_interrupt_roles(sections)
    if profile.strategy in (
        GroupingStrategy.SINGLE_TECH_ARTICLE,
        GroupingStrategy.SINGLE_LEADERSHIP_ESSAY,
        GroupingStrategy.SINGLE_TECH_LONGFORM,
    ):
        return _group_single_merged_article(profile, sections, resolved_roles)
    msg = f"unsupported profile strategy: {profile.strategy!r}"
    raise ValueError(msg)


def _group_single_merged_article(
    profile: SenderProfile,
    sections: list[EmailSection],
    roles: list[InterruptRole],
) -> ProfileRunPlan:
    article_sections: list[EmailSection] = []
    hidden_keys: list[str] = []

    for section, role in zip(sections, roles, strict=True):
        sid = section.section_id.strip()
        if is_strippable_interrupt(role):
            hidden_keys.append(sid)
            continue
        if is_article_body_section(role):
            article_sections.append(section)

    links: list[str] = []
    seen: set[str] = set()
    for section in article_sections:
        for link in section.links:
            url = str(link).strip()
            if url.startswith("https://") and url not in seen:
                seen.add(url)
                links.append(url)

    unit = ContentUnit(
        content_unit_key="u0",
        unit_text="\n\n".join(section.text for section in article_sections if (section.text or "").strip()),
        headings=[section.heading for section in article_sections if section.heading],
        links=links,
        section_keys=[section.section_id.strip() for section in article_sections],
    )
    return ProfileRunPlan(
        profile=profile,
        article_unit=unit,
        hidden_section_keys=tuple(hidden_keys),
        interrupt_roles=tuple(roles),
    )


def structural_counter_evidence(
    profile: SenderProfile,
    sections: list[EmailSection],
    plan: ProfileRunPlan,
) -> str | None:
    """Return a counter-evidence rule id when generic fallback is required."""

    rules = set(profile.counter_evidence_rules)
    article_text = plan.article_unit.unit_text.strip()
    article_chars = len(article_text)

    if "empty_body" in rules and article_chars < ARTICLE_BODY_MIN_CHARS:
        return "empty_body"

    if "promo_dominated" in rules:
        total_chars = sum(len(section.text or "") for section in sections)
        strippable_chars = sum(
            len(section.text or "")
            for section, role in zip(sections, plan.interrupt_roles, strict=True)
            if is_strippable_interrupt(role)
        )
        if total_chars > 0 and strippable_chars / total_chars > PROMO_DOMINATED_RATIO:
            return "promo_dominated"
        if article_chars < ARTICLE_BODY_MIN_CHARS and strippable_chars >= article_chars:
            return "promo_dominated"

    return None


def profile_processor_output_kind(profile: SenderProfile) -> str:
    """Map registry ``processor`` key to persisted ``agent_outputs.kind``."""

    if profile.processor == "technology":
        return "technology"
    if profile.processor == "leadership_essay":
        from app.models.outputs import LEADERSHIP_ESSAY_OUTPUT_KIND

        return LEADERSHIP_ESSAY_OUTPUT_KIND
    if profile.processor == "technical_longform":
        from app.models.outputs import TECHNICAL_LONGFORM_OUTPUT_KIND

        return TECHNICAL_LONGFORM_OUTPUT_KIND
    msg = f"unsupported profile processor: {profile.processor!r}"
    raise ValueError(msg)


def compute_profile_merged_content_hash(
    plan: ProfileRunPlan,
    *,
    section_hashes: dict[str, str],
) -> str:
    """Stable hash over retained article-body sections (strippable interrupts excluded).

    Uses ordered section **content** hashes only — not parser-assigned ``section_key``
    values — so inserting/removing strippable interrupts that renumber keys does not
    invalidate the cache when retained article text is unchanged.
    """

    retained_content_hashes: list[str] = []
    for key in plan.article_unit.section_keys:
        retained_content_hashes.append(section_hashes.get(key.strip(), ""))
    payload = {
        "strategy": plan.profile.strategy.value,
        "content_unit_key": plan.article_unit.content_unit_key,
        "section_content_hashes": retained_content_hashes,
    }
    canon = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def resolve_profile_plan(
    profile: SenderProfile,
    parsed: ParsedHtmlResult,
) -> ProfileRunPlan | None:
    """Build a profile plan or return None when structural counter-evidence fires."""

    roles = detect_interrupt_roles(parsed.sections)
    plan = group_profile_units(profile, parsed.sections, roles=roles)
    reason = structural_counter_evidence(profile, parsed.sections, plan)
    if reason is not None:
        return None
    return plan


__all__ = [
    "ProfileRunPlan",
    "compute_profile_merged_content_hash",
    "group_profile_units",
    "profile_processor_output_kind",
    "resolve_profile_plan",
    "structural_counter_evidence",
]
