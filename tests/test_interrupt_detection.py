from __future__ import annotations

from app.models.section import EmailSection
from app.parsing.interrupt_detection import (
    InterruptRole,
    detect_interrupt_role,
    detect_interrupt_roles,
    explain_interrupt_role,
    is_article_body_section,
    is_strippable_interrupt,
)


def _sec(sid: str, heading: str | None, text: str, *, links: list[str] | None = None) -> EmailSection:
    return EmailSection(section_id=sid, order_index=int(sid[1:]), heading=heading, text=text, links=links or [])


def test_sponsored_heading_is_promo_and_strippable() -> None:
    section = _sec("s2", "WorkOS launches auth.md (Sponsored)", "Product pitch text.")
    decision = explain_interrupt_role(section)
    assert decision.role is InterruptRole.PROMO
    assert decision.rule == "promo:strong_heading_marker"
    assert is_strippable_interrupt(decision.role)
    assert not is_article_body_section(decision.role)


def test_single_weak_promo_keyword_is_unknown_interrupt_and_retained() -> None:
    section = _sec("s5", "Side note", "Mention register once in passing.")
    role = detect_interrupt_role(section)
    assert role is InterruptRole.UNKNOWN_INTERRUPT
    assert is_article_body_section(role)
    assert not is_strippable_interrupt(role)


def test_many_weak_promo_keywords_stay_unknown_not_promo() -> None:
    section = _sec(
        "s2",
        "Workshop",
        "Register for the webinar and RSVP for the workshop.",
    )
    role = detect_interrupt_role(section)
    assert role is InterruptRole.UNKNOWN_INTERRUPT
    assert role is not InterruptRole.PROMO


def test_read_in_app_short_block_is_navigation() -> None:
    section = _sec("s1", "Title", "READ IN APP", links=["https://example.com/read"])
    role = detect_interrupt_role(section)
    assert role is InterruptRole.NAVIGATION


def test_unsubscribe_footer_is_strippable() -> None:
    section = _sec("s9", "Footer", "Click unsubscribe to opt out.")
    role = detect_interrupt_role(section, section_index=9, total_sections=10)
    assert role is InterruptRole.FOOTER


def test_detect_interrupt_roles_preserves_order() -> None:
    sections = [
        _sec("s0", None, "Article dek " * 40),
        _sec("s1", "Chapter", "Body " * 50),
        _sec("s2", "Partner (Sponsored)", "Ad copy"),
    ]
    roles = detect_interrupt_roles(sections)
    assert roles == [
        InterruptRole.NORMAL_CONTENT,
        InterruptRole.NORMAL_CONTENT,
        InterruptRole.PROMO,
    ]
