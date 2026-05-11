from __future__ import annotations

import os

from dotenv import load_dotenv
from openai import OpenAI

from app.llm.client import LLMClient

load_dotenv()


class OpenAIProvider(LLMClient):
    """OpenAI Chat Completions with JSON object mode; models from env or constructor."""

    def __init__(
        self,
        *,
        client: OpenAI | None = None,
        api_key: str | None = None,
        router_model: str | None = None,
        processor_model: str | None = None,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        if client is None:
            if not key:
                raise ValueError("OPENAI_API_KEY is required unless an OpenAI client is injected")
            client = OpenAI(api_key=key)
        self._client = client
        self.router_model = router_model or os.environ.get("ROUTER_MODEL", "gpt-4o-mini")
        self.processor_model = processor_model or os.environ.get(
            "PROCESSOR_MODEL",
            "gpt-4o-mini",
        )

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
