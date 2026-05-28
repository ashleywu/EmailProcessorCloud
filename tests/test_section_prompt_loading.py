"""Section pipeline prompt wiring (system prompt stems + parity with markdown on disk)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents import _prompts as prompt_mod
from app.agents.courses_agent import CoursesProcessorAgent
from app.agents.leadership_agent import LeadershipProcessorAgent
from app.agents.radar_agent import RadarProcessorAgent
from app.agents.router_agent import RouterAgent
from app.agents.technology_agent import TechnologyProcessorAgent
from tests.fakes.llm import ScriptedLLMClient


def test_section_prompt_files_exist_next_to_prompts_package() -> None:
    root: Path = prompt_mod._PROMPTS_DIR
    for stem in prompt_mod.SECTION_PIPELINE_PROMPT_STEMS:
        p = root / f"{stem}.md"
        assert p.is_file(), f"missing {p}"


def test_legacy_prompt_files_exist_but_are_disjoint_from_section_stems() -> None:
    root: Path = prompt_mod._PROMPTS_DIR
    assert set(prompt_mod.LEGACY_EMAIL_LEVEL_PROMPT_STEMS).isdisjoint(
        set(prompt_mod.SECTION_PIPELINE_PROMPT_STEMS),
    )
    for stem in prompt_mod.LEGACY_EMAIL_LEVEL_PROMPT_STEMS:
        assert (root / f"{stem}.md").is_file()


def test_legacy_technology_and_leadership_markdown_declare_deprecated() -> None:
    legacy_t = prompt_mod.load_prompt("technology")[:900]
    legacy_l = prompt_mod.load_prompt("leadership")[:900]
    assert "LEGACY" in legacy_t.upper()
    assert "technology_section.md" in legacy_t
    assert "LEGACY" in legacy_l.upper()
    assert "leadership_section.md" in legacy_l


@pytest.mark.parametrize(
    ("stem", "agent_factory"),
    [
        ("router", lambda llm: RouterAgent(llm, model="stub")),
        ("technology_section", lambda llm: TechnologyProcessorAgent(llm, model="stub")),
        ("leadership_section", lambda llm: LeadershipProcessorAgent(llm, model="stub")),
        ("radar", lambda llm: RadarProcessorAgent(llm, model="stub")),
        ("courses", lambda llm: CoursesProcessorAgent(llm, model="stub")),
    ],
)
def test_section_agents_inline_expected_system_prompts(stem: str, agent_factory) -> None:
    llm = ScriptedLLMClient(['{"placeholder":true}'])
    agent = agent_factory(llm)
    expected = prompt_mod.load_prompt(stem)
    assert agent._prompt == expected
