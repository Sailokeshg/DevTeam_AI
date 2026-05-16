"""LLM provider abstractions and clients."""

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
from app.llm.ollama_client import OllamaLLMProvider, OllamaSettings
from app.llm.service import create_default_llm_provider, generate_text

__all__ = [
    "LLMConnectionError",
    "LLMGenerationRequest",
    "LLMGenerationResponse",
    "LLMMalformedResponseError",
    "LLMModelNotFoundError",
    "LLMProvider",
    "LLMProviderError",
    "LLMTimeoutError",
    "OllamaLLMProvider",
    "OllamaSettings",
    "create_default_llm_provider",
    "generate_text",
]
