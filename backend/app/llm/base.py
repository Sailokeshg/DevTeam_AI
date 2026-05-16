"""Provider-neutral LLM interfaces and error types."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.task import NonEmptyStr


class LLMGenerationRequest(BaseModel):
    """A provider-neutral text generation request."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    prompt: NonEmptyStr
    system_prompt: NonEmptyStr | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)


class LLMGenerationResponse(BaseModel):
    """A provider-neutral text generation response."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    text: str
    model: NonEmptyStr
    provider: NonEmptyStr
    raw: dict[str, Any] = Field(default_factory=dict)


class LLMProviderError(Exception):
    """Base exception for LLM provider failures."""


class LLMConnectionError(LLMProviderError):
    """Raised when the provider cannot be reached."""


class LLMModelNotFoundError(LLMProviderError):
    """Raised when the configured provider model is missing."""


class LLMTimeoutError(LLMProviderError):
    """Raised when a provider request times out."""


class LLMMalformedResponseError(LLMProviderError):
    """Raised when a provider returns an unexpected response shape."""


class LLMProvider(ABC):
    """Abstract interface implemented by all LLM providers."""

    @abstractmethod
    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        """Generate text for a provider-neutral request."""
