from __future__ import annotations

from app.agents._prompts import format_newsletter_text, format_processor_section_plain, load_prompt
from app.llm.client import LLMClient
from app.models.outputs import RadarOutput
from app.models.section import EmailSection


class RadarProcessorAgent:
    def __init__(self, llm: LLMClient, *, model: str) -> None:
        self._llm = llm
        self._model = model
        self._prompt = load_prompt("radar")

    def run(self, *, subject: str | None = None, plain_text: str) -> RadarOutput:
        body = format_newsletter_text(subject=subject, plain_text=plain_text)
        return self._llm.structured_output(
            self._prompt,
            body,
            RadarOutput,
            model=self._model,
        )

    def run_section(self, section: EmailSection, *, subject: str | None = None) -> RadarOutput:
        body = format_processor_section_plain(
            subject=subject,
            section_heading=section.heading,
            plain_text=section.text,
        )
        return self._llm.structured_output(
            self._prompt,
            body,
            RadarOutput,
            model=self._model,
        )
