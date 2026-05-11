from __future__ import annotations

from app.agents._prompts import load_prompt
from app.llm.client import LLMClient
from app.models.outputs import TechnologyOutput
from app.parsing.parser import ParsedHtmlResult


def format_technology_input(parsed: ParsedHtmlResult, *, subject: str | None = None) -> str:
    blocks: list[str] = []
    if subject:
        blocks.append(f"Subject: {subject}")
    if parsed.original_url:
        blocks.append(f"Original URL (hint): {parsed.original_url}")
    blocks.append("Plain text:\n" + parsed.plain_text)
    lines = ["Candidate image_urls (select only from this list, copy URLs exactly):"]
    for i, url in enumerate(parsed.image_urls, start=1):
        lines.append(f"  {i}. {url}")
    blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


class TechnologyProcessorAgent:
    def __init__(self, llm: LLMClient, *, model: str) -> None:
        self._llm = llm
        self._model = model
        self._prompt = load_prompt("technology")

    def run(self, parsed: ParsedHtmlResult, *, subject: str | None = None) -> TechnologyOutput:
        body = format_technology_input(parsed, subject=subject)
        return self._llm.structured_output(
            self._prompt,
            body,
            TechnologyOutput,
            model=self._model,
            validation_context={"allowed_image_urls": list(parsed.image_urls)},
        )
