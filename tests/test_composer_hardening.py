"""Composer diagnostics: mismatched pairs and legacy processor rows."""

from __future__ import annotations

from app.digest.composer import ComposeResult, DigestComposer
from app.models.outputs import (
    CoursesOutput,
    CourseActionItem,
    LeadershipSectionOutput,
    LeadershipSignal,
    RadarItem,
    RadarOutput,
    RouteCategory,
    TechnologySectionOutput,
)
from app.storage.repository import AgentOutputRecord


def test_category_kind_mismatch_skipped_with_warning() -> None:
    bad = AgentOutputRecord(
        id=501,
        email_id=77,
        kind="technology",
        payload=TechnologySectionOutput(
            title="Should not surface",
            core_pain_point="x",
            original_url="https://bad.example/skipped",
            diagrams=[],
        ).model_dump_json(),
        created_at="t",
        email_section_id=900,
        category=RouteCategory.RADAR.value,
        section_order_index=0,
        section_key="s0",
        section_heading="H1",
    )
    result = DigestComposer().compose([bad], subjects={77: "Mail"})
    assert "https://bad.example/skipped" not in result.html
    assert len(result.composition_warnings) == 1
    w = result.composition_warnings[0]
    assert w.startswith("composition_category_kind_mismatch:")
    assert "email_id=77" in w and "email_section_id=900" in w
    assert "kind='technology'" in w and "category='RADAR'" in w


def test_invalid_category_skipped_with_warning() -> None:
    bad = AgentOutputRecord(
        id=502,
        email_id=78,
        kind="radar",
        payload=RadarOutput(summary="unique_radar_bad_cat_token_zz", items=[]).model_dump_json(),
        created_at="t",
        email_section_id=901,
        category="NOT_A_ROUTE_CATEGORY",
        section_order_index=0,
        section_key="s0",
    )
    result = DigestComposer().compose([bad], subjects={78: "Radar mail"})
    assert "unique_radar_bad_cat_token_zz" not in result.html
    assert len(result.composition_warnings) == 1
    assert result.composition_warnings[0].startswith("composition_invalid_category:")
    assert "category='NOT_A_ROUTE_CATEGORY'" in result.composition_warnings[0]


def test_legacy_processor_null_section_skipped_with_warning() -> None:
    legacy = AgentOutputRecord(
        id=503,
        email_id=79,
        kind="technology",
        payload=TechnologySectionOutput(
            title="Whole-email legacy",
            core_pain_point="y",
            original_url="https://legacy.example/old",
            diagrams=[],
        ).model_dump_json(),
        created_at="t",
        email_section_id=None,
        category=RouteCategory.TECHNOLOGY.value,
    )
    result = DigestComposer().compose([legacy], subjects={79: "Legacy subj"})
    assert "https://legacy.example/old" not in result.html
    assert len(result.composition_warnings) == 1
    w = result.composition_warnings[0]
    assert w.startswith("composition_legacy_email_level_processor:")
    assert "email_section_id=null" in w and "kind='technology'" in w


def test_valid_sections_render_when_other_rows_are_skipped() -> None:
    legacy = AgentOutputRecord(
        id=600,
        email_id=55,
        kind="technology",
        payload=TechnologySectionOutput(
            title="Dropped",
            core_pain_point="z",
            original_url="https://drop.example/x",
            diagrams=[],
        ).model_dump_json(),
        created_at="t",
        email_section_id=None,
        category=RouteCategory.TECHNOLOGY.value,
    )
    good = AgentOutputRecord(
        id=601,
        email_id=55,
        kind="technology",
        payload=TechnologySectionOutput(
            title="Kept tile",
            core_pain_point="ok",
            original_url="https://keep.example/y",
            diagrams=[],
        ).model_dump_json(),
        created_at="t",
        email_section_id=1200,
        category=RouteCategory.TECHNOLOGY.value,
        section_order_index=0,
        section_key="sx",
        section_heading="Keeping",
    )
    result = DigestComposer().compose([legacy, good], subjects={55: "Combo"})
    assert "https://keep.example/y" in result.html
    assert "Kept tile" in result.html
    assert "https://drop.example/x" not in result.html
    assert sum(1 for m in result.composition_warnings if m.startswith("composition_legacy_")) == 1


def test_one_email_fanout_multiple_sections_no_warnings() -> None:
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
    result = DigestComposer().compose(rows, subjects={42: "Mega issue"})
    assert isinstance(result, ComposeResult)
    assert result.composition_warnings == ()
    assert "Deep dive" in result.html and "Pulse recap" in result.html and "Trust" in result.html
    assert "https://learn.example/rsvp" in result.html


def test_courses_noise_kind_valid_pair_renders() -> None:
    row = AgentOutputRecord(
        id=700,
        email_id=30,
        kind="noise",
        payload=CoursesOutput(
            summary="Legacy noise body",
            actions=[CourseActionItem(label="Act", url="https://courses.example/a")],
        ).model_dump_json(),
        created_at="t",
        email_section_id=2000,
        category=RouteCategory.COURSES.value,
        section_order_index=0,
        section_key="n0",
    )
    result = DigestComposer().compose([row], subjects={30: "Courses msg"})
    assert "https://courses.example/a" in result.html
    assert result.composition_warnings == ()
