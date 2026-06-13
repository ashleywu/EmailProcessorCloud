"""Read-only profile-path audit for one persisted email."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

from app.parsing.interrupt_detection import (
    InterruptRoleDecision,
    explain_interrupt_roles,
    is_strippable_interrupt,
)
from app.parsing.parser import ParsedHtmlResult, parse_newsletter_html
from app.processing.profile_executor import (
    compute_profile_merged_content_hash,
    group_profile_units,
    profile_processor_output_kind,
    resolve_profile_plan,
    structural_counter_evidence,
)
from app.processing.sender_profiles import SenderProfile, lookup_sender_profile
from app.storage.repository import EmailRecord, StateRepository

_PREVIEW_CHARS = 200


@dataclass(frozen=True, slots=True)
class SectionAuditRow:
    section_key: str
    heading: str | None
    interrupt_role: str
    detection_rule: str
    disposition: str
    char_count: int
    preview: str


def _section_preview(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= _PREVIEW_CHARS:
        return normalized
    return normalized[:_PREVIEW_CHARS]


def _section_disposition(decision: InterruptRoleDecision) -> str:
    return "hidden" if is_strippable_interrupt(decision.role) else "retained"


def build_section_audit_rows(sections: list, decisions: list[InterruptRoleDecision]) -> list[SectionAuditRow]:
    rows: list[SectionAuditRow] = []
    for section, decision in zip(sections, decisions, strict=True):
        text = section.text or ""
        rows.append(
            SectionAuditRow(
                section_key=section.section_id.strip(),
                heading=section.heading,
                interrupt_role=decision.role.value,
                detection_rule=decision.rule,
                disposition=_section_disposition(decision),
                char_count=len(text),
                preview=_section_preview(text),
            ),
        )
    return rows


def format_profile_email_audit(
    *,
    email: EmailRecord,
    parsed: ParsedHtmlResult,
    profile: SenderProfile | None,
    section_rows: list[SectionAuditRow],
    merged_article_section_keys: list[str] | None,
    counter_evidence: str | None,
    profile_plan_active: bool,
    merged_content_hash: str | None = None,
    processor_kind: str | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"email_id={email.id}")
    lines.append(f"message_id={email.message_id}")
    lines.append(f"subject={email.subject or '(none)'}")
    lines.append(f"sender={email.sender or '(none)'}")
    lines.append(f"status={email.status}")
    lines.append(f"section_count={parsed.section_count}")
    if profile is None:
        lines.append("sender_profile=(none)")
    else:
        lines.append(f"sender_profile={profile.sender_email}")
        lines.append(f"grouping_strategy={profile.strategy.value}")
        lines.append(f"default_category={profile.default_category.value}")
        if merged_content_hash:
            lines.append(f"merged_content_hash={merged_content_hash}")
        if processor_kind:
            lines.append(f"processor_kind={processor_kind}")
    if profile is None:
        lines.append("profile_plan=unavailable (no sender profile)")
    elif profile_plan_active:
        lines.append("profile_plan=active")
    else:
        lines.append(f"profile_plan=rejected (counter_evidence={counter_evidence})")
    lines.append("")

    for index, row in enumerate(section_rows):
        lines.append(f"[section {index}] section_key={row.section_key}")
        lines.append(f"  heading={row.heading!r}")
        lines.append(f"  interrupt_role={row.interrupt_role}")
        lines.append(f"  detection_rule={row.detection_rule}")
        lines.append(f"  disposition={row.disposition}")
        lines.append(f"  char_count={row.char_count}")
        lines.append(f"  preview={row.preview!r}")
        lines.append("")

    lines.append("merged_article_section_keys:")
    if merged_article_section_keys is None:
        lines.append("  (none — profile path not active)")
    elif not merged_article_section_keys:
        lines.append("  (empty)")
    else:
        lines.append("  " + ", ".join(merged_article_section_keys))
    return "\n".join(lines) + "\n"


def audit_parsed_profile_email(
    *,
    email: EmailRecord,
    parsed: ParsedHtmlResult,
) -> str:
    profile = lookup_sender_profile(email.sender)
    decisions = explain_interrupt_roles(parsed.sections)
    section_rows = build_section_audit_rows(parsed.sections, decisions)

    merged_keys: list[str] | None = None
    counter_evidence: str | None = None
    profile_plan_active = False
    merged_content_hash: str | None = None
    processor_kind: str | None = None

    if profile is not None:
        roles = [decision.role for decision in decisions]
        plan = group_profile_units(profile, parsed.sections, roles=roles)
        merged_keys = list(plan.article_unit.section_keys)
        counter_evidence = structural_counter_evidence(profile, parsed.sections, plan)
        profile_plan_active = resolve_profile_plan(profile, parsed) is not None
        if profile_plan_active:
            from app.parsing.section_caps import compute_section_content_hash

            section_hashes = {
                section.section_id.strip(): compute_section_content_hash(section)
                for section in parsed.sections
            }
            merged_content_hash = compute_profile_merged_content_hash(
                plan,
                section_hashes=section_hashes,
            )
            processor_kind = profile_processor_output_kind(profile)

    return format_profile_email_audit(
        email=email,
        parsed=parsed,
        profile=profile,
        section_rows=section_rows,
        merged_article_section_keys=merged_keys,
        counter_evidence=counter_evidence,
        profile_plan_active=profile_plan_active,
        merged_content_hash=merged_content_hash,
        processor_kind=processor_kind,
    )


def run_profile_email_audit(
    *,
    email_id: int,
    repo: StateRepository,
    fetch_html: Callable[[str], str],
) -> str:
    email = repo.get_email_by_id(email_id)
    if email is None:
        msg = f"No email row with id={email_id}."
        raise LookupError(msg)

    html = fetch_html(email.message_id)
    parsed = parse_newsletter_html(html)
    return audit_parsed_profile_email(email=email, parsed=parsed)


def audit_profile_email_cli(*, email_id: int, db_path=None) -> int:
    from pathlib import Path

    from pydantic import ValidationError

    from app.config import build_gmail_client, load_settings
    from app.gmail.fetcher import GmailFetcher

    try:
        settings = load_settings()
    except ValidationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    resolved_db = Path(db_path) if db_path is not None else settings.db_path
    repo = StateRepository(resolved_db)
    try:
        client = build_gmail_client(settings)
        fetcher = GmailFetcher(client, senders=(), lookback_days=settings.gmail_lookback_days)
        report = run_profile_email_audit(
            email_id=email_id,
            repo=repo,
            fetch_html=fetcher.fetch_message_html,
        )
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Audit failed: {exc}", file=sys.stderr)
        return 1
    finally:
        repo.close()

    sys.stdout.write(report)
    return 0


__all__ = [
    "SectionAuditRow",
    "audit_parsed_profile_email",
    "audit_profile_email_cli",
    "build_section_audit_rows",
    "format_profile_email_audit",
    "run_profile_email_audit",
]
