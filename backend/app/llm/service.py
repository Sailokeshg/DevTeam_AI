"""Internal service helpers for LLM access."""

from app.llm.base import LLMGenerationRequest, LLMGenerationResponse, LLMProvider
from app.llm.ollama_client import OllamaLLMProvider


def create_default_llm_provider() -> LLMProvider:
    """Create the default local/free LLM provider."""
    return OllamaLLMProvider()


def generate_text(
    prompt: str,
    *,
    provider: LLMProvider | None = None,
    system_prompt: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> LLMGenerationResponse:
    """Generate text through an injected provider or the default Ollama provider."""
    active_provider = provider or create_default_llm_provider()
    request = LLMGenerationRequest(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return active_provider.generate(request)
