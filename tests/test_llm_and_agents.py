from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agents import (
    CoursesProcessorAgent,
    LeadershipProcessorAgent,
    RadarProcessorAgent,
    RouterAgent,
    TechnologyProcessorAgent,
)
from app.llm.client import LLMOutputValidationError, extract_json_object_text
from app.llm.providers.openai_provider import OpenAIProvider
from app.models.outputs import (
    CoursesOutput,
    LeadershipOutput,
    RadarOutput,
    RouterDecision,
    RouteCategory,
    TechnologySectionOutput,
)
from app.models.section import EmailSection
from app.parsing.parser import ParsedHtmlResult
from tests.fakes.llm import ScriptedLLMClient


def test_technology_section_input_includes_candidates() -> None:
    from app.agents._prompts import format_section_https_candidates

    text = format_section_https_candidates(
        subject="S",
        section_plain_text="learn more",
        heading="H",
        section_links=["https://post.example/ep216"],
        original_url_hint=None,
        link_list_title="URLs:",
    )
    assert "https://post.example/ep216" in text


def test_extract_json_object_strips_fence() -> None:
    raw = '```json\n{"category": "COURSES", "confidence": 0.5}\n```'
    assert "category" in extract_json_object_text(raw)


def test_router_decision_schema_from_json() -> None:
    payload = '{"category": "RADAR", "confidence": 0.75, "rationale": "facts"}'
    d = RouterDecision.model_validate_json(payload)
    assert d.category == RouteCategory.RADAR


def test_technology_section_schema_from_json_with_context() -> None:
    payload = (
        '{"title":"t","core_pain_point":"c","original_url":"https://post.example/p","diagrams":[]}'
    )
    TechnologySectionOutput.model_validate_json(
        payload,
        context={"allowed_article_urls": ["https://post.example/p"]},
    )


def test_radar_leadership_noise_schema_from_json() -> None:
    RadarOutput.model_validate_json(
        '{"items": [{"entity": "Co", "impact_or_action": "Shipped v1"}], "summary": null}',
    )
    LeadershipOutput.model_validate_json(
        '{"signals": [{"theme": "t", "insight": "i", "actionable_item": "Schedule a retro"}], '
        '"summary": null, '
        '"roundup_radar": null, '
        '"session_promos": null}',
    )
    CoursesOutput.model_validate_json(
        '{"summary": "Marketing blast.", "actions": [{"label": "x", "url": "https://a.example"}]}',
    )


def test_structured_output_retries_once_then_succeeds() -> None:
    good = '{"category": "COURSES", "confidence": 0.4, "rationale": null}'
    llm = ScriptedLLMClient(["not json", good])
    out = llm.structured_output("sys", "user", RouterDecision, model="m1")
    assert out.category == RouteCategory.COURSES
    assert len(llm.completion_calls) == 2


def test_structured_output_final_validation_failure() -> None:
    llm = ScriptedLLMClient(['not json', '{"category": "COURSES", "confidence": 99}'])
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


def test_technology_section_agent_passes_article_url_context() -> None:
    llm = ScriptedLLMClient(
        [
            '{"title": "Post", "core_pain_point": "Details.", '
            '"original_url": "https://post.example/a", "diagrams": []}',
        ],
    )
    parsed = ParsedHtmlResult(
        plain_text="t",
        plain_text_chars=1,
        links=["https://post.example/a"],
        image_urls=["https://allow.example/a.png"],
        original_url=None,
        sections=[
            EmailSection(
                section_id="s0",
                order_index=0,
                text="section body " * 50,
                links=["https://post.example/a"],
                image_urls=[],
            ),
        ],
    )
    agent = TechnologyProcessorAgent(llm, model="proc-m")
    out = agent.run_section(parsed.sections[0], subject="Sub", parsed_fallback=parsed)
    assert out.original_url == "https://post.example/a"


def test_leadership_and_courses_agents_roundtrip() -> None:
    llm_l = ScriptedLLMClient(
        [
            '{"signals":[{"theme":"t","insight":"i","actionable_item":"Do X","link":"https://course.example/c"}],'
            '"summary":null}',
        ],
    )
    parsed_l = ParsedHtmlResult(
        plain_text="body",
        plain_text_chars=4,
        links=["https://course.example/c"],
        image_urls=[],
        original_url=None,
    )
    LeadershipProcessorAgent(llm_l, model="m").run_section(
        EmailSection(
            section_id="s0",
            order_index=0,
            text="body " * 80,
            links=["https://course.example/c"],
            image_urls=[],
        ),
        subject=None,
        parsed_fallback=parsed_l,
    )
    llm_n = ScriptedLLMClient(['{"summary":"Pure advertisement.","actions":[]}'])
    CoursesProcessorAgent(llm_n, model="m").run_section(
        EmailSection(
            section_id="s0",
            order_index=0,
            text="c " * 80,
            links=[],
            image_urls=[],
        ),
        subject=None,
        parsed_fallback=ParsedHtmlResult(
            plain_text="c",
            plain_text_chars=1,
            links=[],
            image_urls=[],
            original_url=None,
        ),
    )


def test_openai_provider_uses_injected_client_and_models() -> None:
    mock = MagicMock()
    mock.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"category":"COURSES","confidence":0.5}'))],
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
