"""Tests for read-only profile email audit."""

from __future__ import annotations

from app.audit.profile_email import audit_parsed_profile_email, build_section_audit_rows
from app.models.email import EmailInput
from app.models.section import EmailSection
from app.parsing.interrupt_detection import InterruptRole, explain_interrupt_role, explain_interrupt_roles
from app.parsing.parser import ParsedHtmlResult
from app.storage.repository import EmailRecord, StateRepository
from tests.test_ale_sp2 import ale_essay_sections
from tests.test_bytebytego_sp1 import salesforce_163_sections


def test_explain_interrupt_role_reports_detection_rule() -> None:
    section = EmailSection(
        section_id="s2",
        order_index=2,
        heading="Partner cohort (Sponsored)",
        text="Short ad copy.",
    )
    decision = explain_interrupt_role(section)
    assert decision.role is InterruptRole.PROMO
    assert decision.rule == "promo:strong_heading_marker"


def test_build_section_audit_rows_include_disposition_and_preview() -> None:
    sections = ale_essay_sections()
    decisions = explain_interrupt_roles(sections)
    rows = build_section_audit_rows(sections, decisions)

    assert rows[2].section_key == "s2"
    assert rows[2].interrupt_role == "promo"
    assert rows[2].detection_rule == "promo:strong_heading_marker"
    assert rows[2].disposition == "hidden"
    assert rows[2].char_count == len(sections[2].text or "")
    assert len(rows[2].preview) <= 200

    assert rows[0].disposition == "retained"
    assert rows[3].disposition == "retained"


def test_audit_parsed_profile_email_reports_merged_article_keys() -> None:
    sections = ale_essay_sections()
    parsed = ParsedHtmlResult(
        plain_text="",
        plain_text_chars=0,
        links=[],
        image_urls=[],
        sections=sections,
    )
    email = EmailRecord(
        id=7,
        message_id="ale-sp2",
        subject="The Leadership Gap",
        sender="alifeengineered@substack.com",
        status="archived",
    )
    report = audit_parsed_profile_email(email=email, parsed=parsed)

    assert "sender_profile=alifeengineered@substack.com" in report
    assert "profile_plan=active" in report
    assert "section_key=s2" in report
    assert "disposition=hidden" in report
    assert "merged_article_section_keys:" in report
    assert "s0, s1, s3" in report


def test_audit_parsed_profile_email_reports_counter_evidence_rejection() -> None:
    parsed = ParsedHtmlResult(
        plain_text="",
        plain_text_chars=0,
        links=[],
        image_urls=[],
        sections=[
            EmailSection(section_id="s0", order_index=0, heading="(Sponsored)", text="Ad only."),
        ],
    )
    email = EmailRecord(
        id=9,
        message_id="bbg-empty",
        subject="Promo only",
        sender="bytebytego@substack.com",
        status="pending",
    )
    report = audit_parsed_profile_email(email=email, parsed=parsed)

    assert "profile_plan=rejected (counter_evidence=empty_body)" in report
    assert "merged_article_section_keys:" in report
    assert "(empty)" in report


def test_run_profile_email_audit_uses_fetch_html_without_db_writes(tmp_path) -> None:
    repo = StateRepository(tmp_path / "audit.sqlite")
    try:
        email_id = repo.upsert_email(
            EmailInput(
                message_id="audit-msg",
                subject="Audit subject",
                sender="bytebytego@substack.com",
            ),
        )
        sections = salesforce_163_sections()
        html = "<html><body>" + "".join(
            f"<h2>{section.heading}</h2><p>{section.text}</p>" if section.heading else f"<p>{section.text}</p>"
            for section in sections
        ) + "</body></html>"

        from app.audit.profile_email import run_profile_email_audit

        report = run_profile_email_audit(
            email_id=email_id,
            repo=repo,
            fetch_html=lambda _mid: html,
        )
        assert "section_key=s2" in report
        assert "disposition=hidden" in report
        merged_line = report.split("merged_article_section_keys:")[1].strip().splitlines()[0]
        merged_keys = [part.strip() for part in merged_line.removeprefix("  ").split(",")]
        assert "s2" not in merged_keys
        assert merged_keys == [f"s{i}" for i in [0, 1, *range(3, 21)]]

        section_count = repo.connection.execute(
            "SELECT COUNT(*) AS n FROM email_sections WHERE email_id = ?",
            (email_id,),
        ).fetchone()["n"]
        assert section_count == 0
    finally:
        repo.close()
