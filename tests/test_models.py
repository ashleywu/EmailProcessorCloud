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


def test_router_decision_confidence_bounds() -> None:
    RouterDecision(route=RouteCategory.TECHNOLOGY, confidence=0.5)
    with pytest.raises(ValidationError):
        RouterDecision(route=RouteCategory.NOISE, confidence=1.5)


def test_technology_output_nested_diagram() -> None:
    out = TechnologyOutput(
        summary="S",
        key_points=["a"],
        diagram=Diagram(title="D", diagram_type="mermaid", content="graph TD;A-->B"),
    )
    assert out.diagram is not None
    assert out.diagram.diagram_type == "mermaid"


def test_radar_and_leadership_outputs() -> None:
    RadarOutput(items=[RadarItem(title="t", url="https://x.example", note=None)])
    LeadershipOutput(
        signals=[LeadershipSignal(theme="trust", insight="x")],
        summary="s",
    )


def test_noise_output_defaults() -> None:
    n = NoiseOutput(reason="low signal")
    assert n.discard is True


def test_processed_email_digest_optional() -> None:
    ProcessedEmail(
        id=1,
        message_id="mid",
        status="pending",
        digest_id=None,
    )


def test_models_json_roundtrip() -> None:
    rd = RouterDecision(route=RouteCategory.RADAR, confidence=0.9, rationale=None)
    assert RouterDecision.model_validate_json(rd.model_dump_json()) == rd

    ts = datetime.now(timezone.utc)
    ei = EmailInput(message_id="m1", subject="S", body_preview="b", received_at=ts)
    ei2 = EmailInput.model_validate_json(ei.model_dump_json())
    assert ei2.message_id == "m1"
    assert ei2.received_at is not None
