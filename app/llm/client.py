from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMOutputValidationError(Exception):
    """Raised when model output cannot be parsed into the requested Pydantic schema after one retry."""

    def __init__(
        self,
        message: str,
        *,
        last_raw: str | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.last_raw = last_raw
        self.errors = errors


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def extract_json_object_text(raw: str) -> str:
    """Strip optional markdown fences and surrounding whitespace."""
    text = raw.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    return text


class LLMClient(ABC):
    """Language-model façade with structured JSON output and one validation retry."""

    @abstractmethod
    def _completion_json(self, *, system_prompt: str, user_message: str, model: str) -> str:
        """Return model output text (expected to be or contain a single JSON object)."""

    def structured_output(
        self,
        prompt: str,
        input_text: str,
        response_model: type[T],
        *,
        model: str,
        validation_context: dict[str, Any] | None = None,
    ) -> T:
        raw = self._completion_json(system_prompt=prompt, user_message=input_text, model=model)
        try:
            payload = extract_json_object_text(raw)
            return response_model.model_validate_json(payload, context=validation_context)
        except (ValidationError, json.JSONDecodeError) as first:
            suffix = (
                "\n\nThe previous model output did not match the required JSON schema. "
                f"Error details:\n{first}\n"
                "Respond with one JSON object only, no markdown, valid for the schema."
            )
            raw2 = self._completion_json(
                system_prompt=prompt,
                user_message=input_text + suffix,
                model=model,
            )
            try:
                payload2 = extract_json_object_text(raw2)
                return response_model.model_validate_json(payload2, context=validation_context)
            except (ValidationError, json.JSONDecodeError) as second:
                errors: list[dict[str, Any]] | None = None
                if isinstance(second, ValidationError):
                    errors = second.errors()
                raise LLMOutputValidationError(
                    "Structured output failed validation after retry",
                    last_raw=raw2,
                    errors=errors,
                ) from second
