"""Tests for Phase 3 Planner and Architect agents."""

import pytest

from app.agents import AgentOutputError, ArchitectAgent, PlannerAgent
from app.llm import LLMGenerationRequest, LLMGenerationResponse, LLMProvider
from app.schemas.task import TaskList


class FakeLLMProvider(LLMProvider):
    """Queue-based fake LLM provider for deterministic agent tests."""

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


def test_planner_agent_returns_valid_task_list() -> None:
    provider = FakeLLMProvider(
        responses=[
            """
            {
              "tasks": [
                {
                  "id": "task-1",
                  "title": "Add health route",
                  "description": "Add a FastAPI health route.",
                  "type": "feature",
                  "dependencies": [],
                  "acceptance_criteria": ["GET /health returns status ok."]
                },
                {
                  "id": "task-2",
                  "title": "Add route test",
                  "description": "Cover the health route with a backend test.",
                  "type": "test",
                  "dependencies": ["task-1"],
                  "acceptance_criteria": ["The test passes with pytest."]
                }
              ]
            }
            """
        ]
    )
    planner = PlannerAgent(provider)

    task_list = planner.plan(
        user_request="Add a health endpoint.",
        repository_summary="FastAPI backend with pytest tests.",
    )

    assert isinstance(task_list, TaskList)
    assert [task.id for task in task_list.tasks] == ["task-1", "task-2"]
    assert task_list.tasks[1].dependencies == ["task-1"]
    assert "Add a health endpoint" in provider.requests[0].prompt
    assert provider.requests[0].system_prompt is not None
    assert "Planner Agent" in provider.requests[0].system_prompt


def test_planner_agent_rejects_invalid_json() -> None:
    provider = FakeLLMProvider(responses=["This is not JSON."])
    planner = PlannerAgent(provider)

    with pytest.raises(AgentOutputError, match="did not contain a JSON object"):
        planner.plan(user_request="Add a health endpoint.")


def test_planner_agent_rejects_schema_invalid_task_list() -> None:
    provider = FakeLLMProvider(
        responses=[
            """
            {
              "tasks": [
                {
                  "id": "task-1",
                  "title": "Add health route",
                  "description": "Add a FastAPI health route.",
                  "type": "feature",
                  "dependencies": ["missing-task"],
                  "acceptance_criteria": ["GET /health returns status ok."]
                }
              ]
            }
            """
        ]
    )
    planner = PlannerAgent(provider)

    with pytest.raises(AgentOutputError, match="expected schema"):
        planner.plan(user_request="Add a health endpoint.")


def test_architect_agent_returns_valid_architecture_plan_from_fenced_json() -> None:
    provider = FakeLLMProvider(
        responses=[
            """
            ```json
            {
              "summary": "Add the route in the existing API router and cover it with tests.",
              "impacted_files": ["backend/app/api/routes.py", "backend/tests/test_health.py"],
              "design_choices": ["Reuse the existing APIRouter for the endpoint."],
              "risks": ["Keep the response contract stable for callers."],
              "testing_strategy": ["Use TestClient to assert the status code and response body."]
            }
            ```
            """
        ]
    )
    task_list = TaskList.model_validate(
        {
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Add health route",
                    "description": "Add a FastAPI health route.",
                    "type": "feature",
                    "dependencies": [],
                    "acceptance_criteria": ["GET /health returns status ok."],
                }
            ]
        }
    )
    architect = ArchitectAgent(provider)

    plan = architect.design(
        user_request="Add a health endpoint.",
        repository_summary="FastAPI backend with a route module.",
        task_list=task_list,
    )

    assert plan.impacted_files == ["backend/app/api/routes.py", "backend/tests/test_health.py"]
    assert "existing APIRouter" in plan.design_choices[0]
    assert "Task list JSON" in provider.requests[0].prompt
    assert provider.requests[0].system_prompt is not None
    assert "Architect Agent" in provider.requests[0].system_prompt


def test_architect_agent_rejects_schema_invalid_plan() -> None:
    provider = FakeLLMProvider(
        responses=[
            """
            {
              "summary": "Plan without the required testing strategy.",
              "impacted_files": ["backend/app/api/routes.py"],
              "design_choices": ["Reuse existing routes."],
              "risks": ["Missing test plan."]
            }
            """
        ]
    )
    task_list = TaskList.model_validate(
        {
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Add health route",
                    "description": "Add a FastAPI health route.",
                    "type": "feature",
                    "dependencies": [],
                    "acceptance_criteria": ["GET /health returns status ok."],
                }
            ]
        }
    )
    architect = ArchitectAgent(provider)

    with pytest.raises(AgentOutputError, match="expected schema"):
        architect.design(
            user_request="Add a health endpoint.",
            repository_summary="FastAPI backend with a route module.",
            task_list=task_list,
        )
