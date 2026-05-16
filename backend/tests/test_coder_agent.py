"""Tests for the Phase 5 Coder Agent."""

import pytest

from app.agents import AgentOutputError, CoderAgent, RelevantFile
from app.llm import LLMGenerationRequest, LLMGenerationResponse, LLMProvider
from app.schemas.agent_state import ArchitecturePlan
from app.schemas.task import TaskList


class FakeLLMProvider(LLMProvider):
    """Queue-based fake LLM provider for deterministic Coder Agent tests."""

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


def make_task_list() -> TaskList:
    return TaskList.model_validate(
        {
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Update greeting",
                    "description": "Change the greeting response.",
                    "type": "feature",
                    "dependencies": [],
                    "acceptance_criteria": ["Greeting returns the updated phrase."],
                }
            ]
        }
    )


def make_architecture_plan() -> ArchitecturePlan:
    return ArchitecturePlan(
        summary="Update the greeting helper in place.",
        impacted_files=["app.py"],
        design_choices=["Keep the public function signature unchanged."],
        risks=["Avoid changing unrelated behavior."],
        testing_strategy=["Add coverage for the new greeting output."],
    )


def test_coder_agent_generates_valid_unified_diff() -> None:
    provider = FakeLLMProvider(
        responses=[
            """
            ```diff
            diff --git a/app.py b/app.py
            --- a/app.py
            +++ b/app.py
            @@ -1,2 +1,2 @@
             def greet(name: str) -> str:
            -    return f"Hello, {name}!"
            +    return f"Hi, {name}!"
            ```
            """
        ]
    )
    coder = CoderAgent(provider)

    patch = coder.generate_patch(
        user_request="Change the greeting to say Hi.",
        task_list=make_task_list(),
        architecture_plan=make_architecture_plan(),
        relevant_files=[
            RelevantFile(
                path="app.py",
                content='def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
            )
        ],
    )

    assert patch.startswith("diff --git a/app.py b/app.py")
    assert '+    return f"Hi, {name}!"' in patch
    assert "Change the greeting" in provider.requests[0].prompt
    assert "Task list JSON" in provider.requests[0].prompt
    assert "Architecture plan JSON" in provider.requests[0].prompt
    assert "File: app.py" in provider.requests[0].prompt


def test_coder_agent_rejects_non_patch_output() -> None:
    provider = FakeLLMProvider(responses=["I would edit app.py by changing the greeting."])
    coder = CoderAgent(provider)

    with pytest.raises(AgentOutputError, match="did not contain a unified diff"):
        coder.generate_patch(
            user_request="Change the greeting to say Hi.",
            task_list=make_task_list(),
            architecture_plan=make_architecture_plan(),
            relevant_files=[],
        )
