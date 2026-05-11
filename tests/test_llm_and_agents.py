from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agents import (
    LeadershipProcessorAgent,
    NoiseProcessorAgent,
    RadarProcessorAgent,
    RouterAgent,
    TechnologyProcessorAgent,
)
from app.llm.client import LLMOutputValidationError, extract_json_object_text
from app.llm.providers.openai_provider import OpenAIProvider
from app.models.outputs import (
    LeadershipOutput,
    NoiseOutput,
    RadarOutput,
    RouterDecision,
    RouteCategory,
    TechnologyOutput,
)
from app.parsing.parser import ParsedHtmlResult
from tests.fakes.llm import ScriptedLLMClient


def test_extract_json_object_strips_fence() -> None:
    raw = '```json\n{"category": "NOISE", "confidence": 0.5}\n```'
    assert "category" in extract_json_object_text(raw)


def test_router_decision_schema_from_json() -> None:
    payload = '{"category": "RADAR", "confidence": 0.75, "rationale": "facts"}'
    d = RouterDecision.model_validate_json(payload)
    assert d.category == RouteCategory.RADAR


def test_technology_schema_from_json_with_context() -> None:
    payload = (
        '{"core_pain_point": "latency", "diagrams": [], '
        '"selected_image_urls": ["https://cdn.example/x.png"]}'
    )
    TechnologyOutput.model_validate_json(
        payload,
        context={"allowed_image_urls": ["https://cdn.example/x.png"]},
    )


def test_radar_leadership_noise_schema_from_json() -> None:
    RadarOutput.model_validate_json(
        '{"items": [{"entity": "Co", "impact_or_action": "Shipped v1"}], "summary": null}',
    )
    LeadershipOutput.model_validate_json(
        '{"signals": [{"theme": "t", "insight": "i", "actionable_item": "Schedule a retro"}], '
        '"summary": null}',
    )
    NoiseOutput.model_validate_json('{"reason": "Empty marketing blast.", "discard": true}')


def test_structured_output_retries_once_then_succeeds() -> None:
    good = '{"category": "NOISE", "confidence": 0.4, "rationale": null}'
    llm = ScriptedLLMClient(["not json", good])
    out = llm.structured_output("sys", "user", RouterDecision, model="m1")
    assert out.category == RouteCategory.NOISE
    assert len(llm.completion_calls) == 2


def test_structured_output_final_validation_failure() -> None:
    llm = ScriptedLLMClient(['not json', '{"category": "NOISE", "confidence": 99}'])
    with pytest.raises(LLMOutputValidationError) as ei:
        llm.structured_output("sys", "user", RouterDecision, model="m1")
    assert ei.value.last_raw is not None
    assert len(llm.completion_calls) == 2


def test_router_agent_invokes_model_name() -> None:
    llm = ScriptedLLMClient(
        ['{"category": "TECHNOLOGY", "confidence": 0.8, "rationale": null}'],
    )
    agent = RouterAgent(llm, model="router-m")
    agent.run(subject="S", plain_text="body")
    assert llm.completion_calls[0][2] == "router-m"


def test_technology_agent_passes_image_url_context() -> None:
    llm = ScriptedLLMClient(
        [
            '{"core_pain_point": "p", "diagrams": [], '
            '"selected_image_urls": ["https://allow.example/a.png"]}',
        ],
    )
    parsed = ParsedHtmlResult(
        plain_text="t",
        plain_text_chars=1,
        links=[],
        image_urls=["https://allow.example/a.png"],
        original_url=None,
    )
    agent = TechnologyProcessorAgent(llm, model="proc-m")
    out = agent.run(parsed, subject="Sub")
    assert out.selected_image_urls == ["https://allow.example/a.png"]


def test_leadership_and_noise_agents_roundtrip() -> None:
    llm_l = ScriptedLLMClient(
        [
            '{"signals":[{"theme":"t","insight":"i","actionable_item":"Do X"}],'
            '"summary":null}',
        ],
    )
    LeadershipProcessorAgent(llm_l, model="m").run(subject=None, plain_text="b")
    llm_n = ScriptedLLMClient(['{"reason":"Pure advertisement.","discard":true}'])
    NoiseProcessorAgent(llm_n, model="m").run(subject=None, plain_text="c")


def test_openai_provider_uses_injected_client_and_models() -> None:
    mock = MagicMock()
    mock.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"category":"NOISE","confidence":0.5}'))],
    )
    prov = OpenAIProvider(
        client=mock,
        router_model="my-router",
        processor_model="my-proc",
    )
    RouterAgent(prov, model=prov.router_model).run(subject=None, plain_text="x")
    mock.chat.completions.create.assert_called_once()
    call_kw = mock.chat.completions.create.call_args.kwargs
    assert call_kw["model"] == "my-router"

    mock.chat.completions.create.return_value = MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(
                    content='{"items":[],"summary":null}',
                ),
            ),
        ],
    )
    RadarProcessorAgent(prov, model=prov.processor_model).run(subject=None, plain_text="z")
    assert mock.chat.completions.create.call_args.kwargs["model"] == "my-proc"
