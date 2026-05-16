"""Shared parsing helpers for structured agent responses."""

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)


class AgentOutputError(ValueError):
    """Raised when an agent response cannot be parsed into the expected schema."""


def parse_json_model(output: str, model_type: type[ModelT], output_name: str) -> ModelT:
    """Parse an LLM response into a Pydantic model with useful error context."""
    json_text = extract_json_object(output)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise AgentOutputError(f"{output_name} was not valid JSON: {exc.msg}") from exc

    try:
        return model_type.model_validate(data)
    except ValidationError as exc:
        raise AgentOutputError(f"{output_name} did not match the expected schema: {exc}") from exc


def extract_json_object(output: str) -> str:
    """Extract JSON from a raw LLM response, including fenced JSON blocks."""
    text = output.strip()

    fenced_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        return fenced_match.group(1).strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    object_start = text.find("{")
    object_end = text.rfind("}")
    if object_start == -1 or object_end == -1 or object_end <= object_start:
        raise AgentOutputError("Agent response did not contain a JSON object")

    return text[object_start : object_end + 1]
