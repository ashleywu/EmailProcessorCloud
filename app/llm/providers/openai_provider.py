from __future__ import annotations

from openai import OpenAI

from app.llm.client import LLMClient


class OpenAIProvider(LLMClient):
    """OpenAI Chat Completions with JSON object mode; keys and models come from Settings."""

    def __init__(
        self,
        *,
        client: OpenAI | None = None,
        api_key: str | None = None,
        router_model: str = "gpt-4o-mini",
        processor_model: str = "gpt-4o-mini",
    ) -> None:
        if client is None:
            if not api_key:
                raise ValueError("api_key is required unless an OpenAI client is injected")
            client = OpenAI(api_key=api_key)
        self._client = client
        self.router_model = router_model
        self.processor_model = processor_model

    def _completion_json(self, *, system_prompt: str, user_message: str, model: str) -> str:
        resp = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        choice = resp.choices[0].message.content
        return (choice or "").strip()
