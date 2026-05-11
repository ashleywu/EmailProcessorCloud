from __future__ import annotations

from app.llm.client import LLMClient


class ScriptedLLMClient(LLMClient):
    """Deterministic LLM for tests: pops scripted response strings per completion call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.completion_calls: list[tuple[str, str, str]] = []

    def _completion_json(self, *, system_prompt: str, user_message: str, model: str) -> str:
        self.completion_calls.append((system_prompt, user_message, model))
        if not self._responses:
            raise RuntimeError("exhausted scripted LLM responses")
        return self._responses.pop(0)
