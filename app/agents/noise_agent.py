from __future__ import annotations

from app.agents._prompts import format_newsletter_text, load_prompt
from app.llm.client import LLMClient
from app.models.outputs import NoiseOutput


class NoiseProcessorAgent:
    def __init__(self, llm: LLMClient, *, model: str) -> None:
        self._llm = llm
        self._model = model
        self._prompt = load_prompt("noise")

    def run(self, *, subject: str | None = None, plain_text: str) -> NoiseOutput:
        body = format_newsletter_text(subject=subject, plain_text=plain_text)
        return self._llm.structured_output(
            self._prompt,
            body,
            NoiseOutput,
            model=self._model,
        )
