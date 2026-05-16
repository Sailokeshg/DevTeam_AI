"""Ollama-backed LLM provider implementation."""

import os
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.llm.base import (
    LLMConnectionError,
    LLMGenerationRequest,
    LLMGenerationResponse,
    LLMMalformedResponseError,
    LLMModelNotFoundError,
    LLMProvider,
    LLMProviderError,
    LLMTimeoutError,
)
from app.schemas.task import NonEmptyStr

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 30.0


class OllamaSettings(BaseModel):
    """Environment-driven Ollama configuration."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    base_url: NonEmptyStr = DEFAULT_OLLAMA_BASE_URL
    model: NonEmptyStr = DEFAULT_OLLAMA_MODEL
    timeout_seconds: float = Field(default=DEFAULT_OLLAMA_TIMEOUT_SECONDS, gt=0)

    @classmethod
    def from_env(cls) -> "OllamaSettings":
        """Create settings from environment variables."""
        timeout_seconds = float(
            os.getenv("OLLAMA_TIMEOUT_SECONDS", str(DEFAULT_OLLAMA_TIMEOUT_SECONDS))
        )
        return cls(
            base_url=os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
            model=os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
            timeout_seconds=timeout_seconds,
        )

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        """Normalize URLs so endpoint construction stays predictable."""
        return value.rstrip("/")


class OllamaLLMProvider(LLMProvider):
    """LLM provider that calls a local Ollama `/api/generate` endpoint."""

    provider_name = "ollama"

    def __init__(self, settings: OllamaSettings | None = None, client: httpx.Client | None = None):
        self.settings = settings or OllamaSettings.from_env()
        self._client = client or httpx.Client()

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        """Generate text with Ollama and normalize common provider failures."""
        payload = self._build_payload(request)

        try:
            response = self._client.post(
                f"{self.settings.base_url}/api/generate",
                json=payload,
                timeout=self.settings.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama request timed out after {self.settings.timeout_seconds} seconds"
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                f"Could not connect to Ollama at {self.settings.base_url}. "
                "Start Ollama with `ollama serve` and confirm the base URL."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(f"Ollama request failed: {exc}") from exc

        self._raise_for_provider_error(response)
        data = self._parse_response(response)
        text = data.get("response")

        if not isinstance(text, str):
            raise LLMMalformedResponseError("Ollama response did not include a string `response`")

        model = data.get("model")
        return LLMGenerationResponse(
            text=text,
            model=model if isinstance(model, str) and model else self.settings.model,
            provider=self.provider_name,
            raw=data,
        )

    def _build_payload(self, request: LLMGenerationRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "prompt": request.prompt,
            "stream": False,
        }

        if request.system_prompt is not None:
            payload["system"] = request.system_prompt

        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        if options:
            payload["options"] = options

        return payload

    def _raise_for_provider_error(self, response: httpx.Response) -> None:
        body = response.text.lower()

        if response.status_code == 404 or (
            response.status_code == 400 and "model" in body and "not found" in body
        ):
            raise LLMModelNotFoundError(
                f"Ollama model `{self.settings.model}` was not found. "
                f"Install it with `ollama pull {self.settings.model}`."
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"Ollama returned HTTP {response.status_code}: {response.text}"
            ) from exc

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMMalformedResponseError("Ollama returned non-JSON response data") from exc

        if not isinstance(data, dict):
            raise LLMMalformedResponseError("Ollama response JSON must be an object")

        return data
