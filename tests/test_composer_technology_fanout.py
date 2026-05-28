"""Digest composer aggregates **section-scoped** processor payloads."""

from __future__ import annotations

from app.digest.composer import DigestComposer
from app.models.outputs import (
    CoursesOutput,
    CourseActionItem,
    CoursePromoBlock,
    LeadershipSectionOutput,
    LeadershipSignal,
    RadarItem,
    RadarOutput,
    RouteCategory,
    TechnologySectionOutput,
)
from app.storage.repository import AgentOutputRecord


def _tech_row(
    *,
    rid: int,
    eid: int,
    sec_id: int,
    heading: str | None,
    order_idx: int,
    title: str,
    url: str,
    cpp: str,
) -> AgentOutputRecord:
    return AgentOutputRecord(
        id=rid,
        email_id=eid,
        kind="technology",
        payload=TechnologySectionOutput(
            title=title,
            core_pain_point=cpp,
            original_url=url,
            diagrams=[],
        ).model_dump_json(),
        created_at="t",
        email_section_id=sec_id,
        category=RouteCategory.TECHNOLOGY.value,
        section_key=f"s{order_idx}",
        section_order_index=order_idx,
        section_heading=heading,
    )


def test_two_technology_sections_yield_two_technical_index_cards() -> None:
    html = DigestComposer().compose(
        [
            _tech_row(
                rid=1,
                eid=7,
                sec_id=10,
                heading="Rust",
                order_idx=0,
                title="Async",
                url="https://ex.example/async",
                cpp="Concurrency traps.",
            ),
            _tech_row(
                rid=2,
                eid=7,
                sec_id=11,
                heading="Systems",
                order_idx=1,
                title="BPF",
                url="https://ex.example/bpf",
                cpp="Kernel introspection.",
            ),
        ],
        subjects={7: "Mixed newsletter"},
    ).html
    assert html.count("https://ex.example/async") >= 1
    assert html.count("https://ex.example/bpf") >= 1
    assert html.count("Concurrency traps.") >= 1
    assert html.count("Mixed newsletter") >= 1


def test_mixed_categories_from_one_email_fan_into_sections() -> None:
    rows = [
        AgentOutputRecord(
            id=11,
            email_id=42,
            kind="technology",
            payload=TechnologySectionOutput(
                title="Deep dive",
                core_pain_point="Latency.",
                original_url="https://ex.example/long",
                diagrams=[],
            ).model_dump_json(),
            created_at="t",
            email_section_id=100,
            category=RouteCategory.TECHNOLOGY.value,
            section_order_index=0,
            section_key="s0",
            section_heading="Tech block",
        ),
        AgentOutputRecord(
            id=12,
            email_id=42,
            kind="radar",
            payload=RadarOutput(
                summary="Pulse recap",
                items=[RadarItem(entity="Co", impact_or_action="Shipped!", url=None)],
            ).model_dump_json(),
            created_at="t",
            email_section_id=101,
            category=RouteCategory.RADAR.value,
            section_order_index=1,
            section_key="s1",
            section_heading="Radar block",
        ),
        AgentOutputRecord(
            id=13,
            email_id=42,
            kind="leadership",
            payload=LeadershipSectionOutput(
                signals=[
                    LeadershipSignal(
                        theme="Trust",
                        insight="Signal early.",
                        actionable_item="Post weekly updates.",
                        link=None,
                    ),
                ],
                summary=None,
            ).model_dump_json(),
            created_at="t",
            email_section_id=102,
            category=RouteCategory.LEADERSHIP.value,
            section_order_index=2,
            section_key="s2",
            section_heading=None,
        ),
        AgentOutputRecord(
            id=14,
            email_id=42,
            kind="courses",
            payload=CoursesOutput(
                summary="RSVP reminder",
                actions=[CourseActionItem(label="Join", url="https://learn.example/rsvp")],
            ).model_dump_json(),
            created_at="t",
            email_section_id=103,
            category=RouteCategory.COURSES.value,
            section_order_index=3,
            section_key="s3",
            section_heading="Promo",
        ),
    ]
    html = DigestComposer().compose(rows, subjects={42: "Mega issue"}).html
    assert "Deep dive" in html
    assert "Pulse recap" in html
    assert "Trust" in html
    assert "Promotions" in html or "Courses" in html
    assert "https://learn.example/rsvp" in html


def test_promo_blocks_still_render() -> None:
    rows = [
        AgentOutputRecord(
            id=1,
            email_id=9,
            kind="courses",
            payload=CoursesOutput(
                summary="",
                promo_blocks=[
                    CoursePromoBlock(
                        text="Executive AI Sessions on June 2.",
                        cta=CourseActionItem(label="Learn more & register", url="https://events.example/reg"),
                    ),
                    CoursePromoBlock(
                        text="Subscriber meetup in Brooklyn on June 3.",
                        cta=CourseActionItem(label="Learn more & RSVP", url="https://events.example/rsvp"),
                    ),
                ],
            ).model_dump_json(),
            created_at="t",
            email_section_id=501,
            category=RouteCategory.COURSES.value,
            section_order_index=0,
            section_key="s0",
        ),
    ]
    html = DigestComposer().compose(rows, subjects={9: "Session mail"}).html
    assert "Executive AI Sessions" in html
    assert "Brooklyn" in html
    assert html.index("Executive AI Sessions") < html.index("https://events.example/reg")
