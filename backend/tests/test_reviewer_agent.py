"""Tests for the Phase 8 Reviewer Agent."""

import pytest

from app.agents import AgentOutputError, ReviewerAgent
from app.llm import LLMGenerationRequest, LLMGenerationResponse, LLMProvider
from app.schemas.agent_state import (
    ArchitecturePlan,
    StaticAnalysisResult,
)
from app.schemas.agent_state import (
    TestResult as AgentTestResult,
)


class FakeLLMProvider(LLMProvider):
    """Queue-based fake LLM provider for deterministic Reviewer Agent tests."""

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.requests: list[LLMGenerationRequest] = []

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        self.requests.append(request)
        return LLMGenerationResponse(
            text=self.responses.pop(0),
            model="fake-model",
            provider="fake",
        )


def make_architecture_plan() -> ArchitecturePlan:
    return ArchitecturePlan(
        summary="Add endpoint tests.",
        impacted_files=["app/main.py", "tests/test_app.py"],
        design_choices=["Use existing FastAPI route patterns."],
        risks=["Keep response contract stable."],
        testing_strategy=["Use pytest and TestClient."],
    )


def test_reviewer_agent_returns_structured_review_result() -> None:
    provider = FakeLLMProvider(
        responses=[
            """
            {
              "approved": true,
              "issues": [],
              "recommended_next_action": "approve",
              "summary": "The implementation satisfies the request and checks passed."
            }
            """
        ]
    )
    reviewer = ReviewerAgent(provider)

    result = reviewer.review(
        user_request="Add tests for /ping.",
        architecture_plan=make_architecture_plan(),
        code_diff="diff --git a/tests/test_app.py b/tests/test_app.py",
        test_results=[
            AgentTestResult(
                command="pytest",
                success=True,
                passed_count=1,
                failed_count=0,
            )
        ],
        static_analysis_results=[
            StaticAnalysisResult(
                tool="ruff",
                command="ruff check .",
                success=True,
            )
        ],
    )

    assert result.approved is True
    assert result.recommended_next_action == "approve"
    assert "Code diff" in provider.requests[0].prompt
    assert "Test results JSON" in provider.requests[0].prompt
    assert "Static-analysis results JSON" in provider.requests[0].prompt


def test_reviewer_agent_rejects_schema_invalid_output() -> None:
    provider = FakeLLMProvider(responses=['{"approved": false}'])
    reviewer = ReviewerAgent(provider)

    with pytest.raises(AgentOutputError, match="expected schema"):
        reviewer.review(
            user_request="Add tests for /ping.",
            architecture_plan=make_architecture_plan(),
            code_diff="",
            test_results=[],
            static_analysis_results=[],
        )
