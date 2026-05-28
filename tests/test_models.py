from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.digest import ProcessedEmail
from app.models.email import EmailInput
from app.models.outputs import (
    CourseActionItem,
    CoursePromoBlock,
    CoursesOutput,
    Diagram,
    LeadershipOutput,
    LeadershipSignal,
    RadarItem,
    RadarOutput,
    RouterDecision,
    RouteCategory,
    TechnologyOutput,
)


def test_email_input_rejects_empty_message_id() -> None:
    with pytest.raises(ValidationError):
        EmailInput(message_id="")


def test_email_input_accepts_sender() -> None:
    e = EmailInput(message_id="m1", sender="Bob <bob@example.com>")
    assert e.sender == "Bob <bob@example.com>"


def test_router_decision_coerces_legacy_noise_category_json() -> None:
    d = RouterDecision.model_validate_json(
        '{"category": "NOISE", "confidence": 0.5, "rationale": null}',
    )
    assert d.category == RouteCategory.COURSES


def test_router_decision_confidence_bounds() -> None:
    RouterDecision(category=RouteCategory.TECHNOLOGY, confidence=0.5)
    with pytest.raises(ValidationError):
        RouterDecision(category=RouteCategory.COURSES, confidence=1.5)


def test_technology_output_diagrams_and_images() -> None:
    out = TechnologyOutput(
        core_pain_point="Short pain point text",
        diagrams=[Diagram(title="D", diagram_type="mermaid", content="graph TD;A-->B")],
        selected_image_urls=[],
    )
    assert out.diagrams[0].diagram_type == "mermaid"


def test_technology_selected_urls_must_match_candidates() -> None:
    TechnologyOutput.model_validate(
        {
            "core_pain_point": "x",
            "selected_image_urls": ["https://ok.example/a.png"],
        },
        context={"allowed_image_urls": ["https://ok.example/a.png"]},
    )
    with pytest.raises(ValidationError):
        TechnologyOutput.model_validate(
            {
                "core_pain_point": "x",
                "selected_image_urls": ["https://evil.example/b.png"],
            },
            context={"allowed_image_urls": ["https://ok.example/a.png"]},
        )


def test_radar_and_leadership_outputs() -> None:
    RadarOutput(
        items=[
            RadarItem(
                entity="Acme",
                impact_or_action="Shipped API v2.",
                url="https://x.example",
            ),
        ],
    )
    LeadershipOutput(
        signals=[
            LeadershipSignal(
                theme="trust",
                insight="Clear expectations reduce thrash.",
                actionable_item="Add a 10m agenda template to recurring 1:1s.",
                link="https://training.example/start",
            ),
        ],
        summary="s",
    )


def test_courses_legacy_noise_json_maps_to_summary() -> None:
    n = CoursesOutput.model_validate_json(
        '{"reason": "low signal newsletter with no facts", "discard": true}',
    )
    assert "low signal newsletter" in n.summary
    assert n.actions == []


def test_courses_multiline_legacy_reason_normally_single_line_summary() -> None:
    """Multiline legacy ``reason`` is flattened rather than rejected."""

    co = CoursesOutput.model_validate_json('{"reason": "line1\\nline2", "discard": true}')
    assert "line1" in co.summary and "line2" in co.summary


def test_courses_output_rejects_totally_empty() -> None:
    with pytest.raises(ValidationError):
        CoursesOutput(summary="", actions=[], promo_blocks=[])


def test_courses_promo_blocks_allowlisted() -> None:
    CoursesOutput.model_validate(
        {
            "summary": "",
            "promo_blocks": [
                {"text": "Event A", "cta": {"label": "RSVP", "url": "https://a.example/x"}},
                {"text": "Event B", "cta": {"label": "Register", "url": "https://b.example/y"}},
            ],
        },
        context={"allowed_action_urls": ["https://a.example/x", "https://b.example/y"]},
    )
    with pytest.raises(ValidationError):
        CoursesOutput.model_validate(
            {
                "summary": "",
                "promo_blocks": [
                    {"text": "Ev", "cta": {"label": "x", "url": "https://evil.example/z"}},
                ],
            },
            context={"allowed_action_urls": ["https://allow.example/o"]},
        )


def test_processed_email_digest_optional() -> None:
    ProcessedEmail(
        id=1,
        message_id="mid",
        status="pending",
        digest_id=None,
    )


def test_models_json_roundtrip() -> None:
    rd = RouterDecision(category=RouteCategory.RADAR, confidence=0.9, rationale=None)
    assert RouterDecision.model_validate_json(rd.model_dump_json()) == rd

    ts = datetime.now(timezone.utc)
    ei = EmailInput(message_id="m1", subject="S", body_preview="b", received_at=ts)
    ei2 = EmailInput.model_validate_json(ei.model_dump_json())
    assert ei2.message_id == "m1"
    assert ei2.received_at is not None
