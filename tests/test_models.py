from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.digest import ProcessedEmail
from app.models.email import EmailInput
from app.models.outputs import (
    Diagram,
    LeadershipOutput,
    LeadershipSignal,
    NoiseOutput,
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


def test_router_decision_confidence_bounds() -> None:
    RouterDecision(category=RouteCategory.TECHNOLOGY, confidence=0.5)
    with pytest.raises(ValidationError):
        RouterDecision(category=RouteCategory.NOISE, confidence=1.5)


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


def test_noise_output_defaults() -> None:
    n = NoiseOutput(reason="low signal newsletter with no facts")
    assert n.discard is True


def test_noise_rejects_multiline_reason() -> None:
    with pytest.raises(ValidationError):
        NoiseOutput(reason="line1\nline2")


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
