from __future__ import annotations

from app.agents._prompts import format_router_section_input, load_prompt
from app.llm.client import LLMClient
from app.models.outputs import RouterDecision, RouterLLMDecision


class RouterAgent:
    def __init__(self, llm: LLMClient, *, model: str) -> None:
        self._llm = llm
        self._model = model
        self._prompt = load_prompt("router")

    def run(
        self,
        *,
        subject: str | None = None,
        plain_text: str,
        section_heading: str | None = None,
    ) -> RouterDecision:
        body = format_router_section_input(
            subject=subject,
            section_heading=section_heading,
            plain_text=plain_text,
        )
        return self._llm.structured_output(
            self._prompt,
            body,
            RouterLLMDecision,
            model=self._model,
        ).to_router_decision()
