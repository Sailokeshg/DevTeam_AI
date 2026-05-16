"""Tests for the Phase 2 LLM provider abstraction and Ollama client."""

import json
from typing import Any

import httpx
import pytest

from app.llm import (
    LLMConnectionError,
    LLMGenerationRequest,
    LLMGenerationResponse,
    LLMMalformedResponseError,
    LLMModelNotFoundError,
    LLMProvider,
    LLMTimeoutError,
    OllamaLLMProvider,
    OllamaSettings,
    generate_text,
)


class MockLLMProvider(LLMProvider):
    """Simple provider used by tests so Ollama is never required."""

    def __init__(self, text: str = "mock response"):
        self.text = text
        self.requests: list[LLMGenerationRequest] = []

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        self.requests.append(request)
        return LLMGenerationResponse(text=self.text, model="mock-model", provider="mock")


def test_generate_text_uses_injected_mock_provider() -> None:
    provider = MockLLMProvider(text="planned output")

    response = generate_text(
        "Create a task list.",
        provider=provider,
        system_prompt="You are a planner.",
        temperature=0.2,
        max_tokens=128,
    )

    assert response.text == "planned output"
    assert response.provider == "mock"
    assert provider.requests == [
        LLMGenerationRequest(
            prompt="Create a task list.",
            system_prompt="You are a planner.",
            temperature=0.2,
            max_tokens=128,
        )
    ]


def test_ollama_settings_can_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "5")

    settings = OllamaSettings.from_env()

    assert settings.base_url == "http://localhost:11434"
    assert settings.model == "mistral"
    assert settings.timeout_seconds == 5


def test_ollama_provider_sends_expected_generate_request() -> None:
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content.decode("utf-8"))
        assert request.url.path == "/api/generate"
        return httpx.Response(200, json={"model": "llama3.1", "response": "Hello from Ollama"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OllamaLLMProvider(
        settings=OllamaSettings(base_url="http://ollama.test", model="llama3.1"),
        client=client,
    )

    response = provider.generate(
        LLMGenerationRequest(
            prompt="Say hello.",
            system_prompt="Be concise.",
            temperature=0.1,
            max_tokens=20,
        )
    )

    assert response.text == "Hello from Ollama"
    assert response.model == "llama3.1"
    assert response.provider == "ollama"
    assert captured_payload == {
        "model": "llama3.1",
        "prompt": "Say hello.",
        "stream": False,
        "system": "Be concise.",
        "options": {"temperature": 0.1, "num_predict": 20},
    }


def test_ollama_provider_raises_connection_error_when_ollama_is_down() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = OllamaLLMProvider(
        settings=OllamaSettings(base_url="http://ollama.test", model="llama3.1"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMConnectionError, match="Could not connect to Ollama"):
        provider.generate(LLMGenerationRequest(prompt="Hello"))


def test_ollama_provider_raises_model_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text='model "missing" not found')

    provider = OllamaLLMProvider(
        settings=OllamaSettings(base_url="http://ollama.test", model="missing"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMModelNotFoundError, match="ollama pull missing"):
        provider.generate(LLMGenerationRequest(prompt="Hello"))


def test_ollama_provider_raises_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = OllamaLLMProvider(
        settings=OllamaSettings(base_url="http://ollama.test", model="llama3.1"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMTimeoutError, match="timed out"):
        provider.generate(LLMGenerationRequest(prompt="Hello"))


def test_ollama_provider_rejects_malformed_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    provider = OllamaLLMProvider(
        settings=OllamaSettings(base_url="http://ollama.test", model="llama3.1"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMMalformedResponseError, match="non-JSON"):
        provider.generate(LLMGenerationRequest(prompt="Hello"))


def test_ollama_provider_rejects_missing_response_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "llama3.1"})

    provider = OllamaLLMProvider(
        settings=OllamaSettings(base_url="http://ollama.test", model="llama3.1"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMMalformedResponseError, match="string `response`"):
        provider.generate(LLMGenerationRequest(prompt="Hello"))
