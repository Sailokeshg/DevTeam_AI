"""Tests for the Phase 6 Tester Agent."""

import shutil
from pathlib import Path

import pytest

from app.agents import AgentOutputError, RelevantFile
from app.agents import TesterAgent as DevTeamTesterAgent
from app.llm import LLMGenerationRequest, LLMGenerationResponse, LLMProvider
from app.schemas.agent_state import ArchitecturePlan
from app.schemas.task import TaskList
from app.tools import apply_unified_diff, run_pytest


class FakeLLMProvider(LLMProvider):
    """Queue-based fake LLM provider for deterministic Tester Agent tests."""

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
                    "title": "Cover ping endpoint",
                    "description": "Add pytest coverage for the demo endpoint.",
                    "type": "test",
                    "dependencies": [],
                    "acceptance_criteria": ["pytest covers the /ping endpoint."],
                }
            ]
        }
    )


def make_architecture_plan() -> ArchitecturePlan:
    return ArchitecturePlan(
        summary="Use FastAPI TestClient for endpoint coverage.",
        impacted_files=["tests/test_app.py"],
        design_choices=["Keep tests local and deterministic."],
        risks=["Ensure imports work from the repository root."],
        testing_strategy=["Assert HTTP status and response body for /ping."],
    )


def test_tester_agent_generates_valid_pytest_patch() -> None:
    provider = FakeLLMProvider(responses=[demo_test_patch()])
    tester = DevTeamTesterAgent(provider)

    patch = tester.generate_test_patch(
        user_request="Add tests for the /ping endpoint.",
        task_list=make_task_list(),
        architecture_plan=make_architecture_plan(),
        relevant_files=[
            RelevantFile(
                path="app/main.py",
                content="from fastapi import FastAPI\n\napp = FastAPI()\n",
            )
        ],
    )

    assert patch.startswith("diff --git a/tests/test_app.py b/tests/test_app.py")
    assert "TestClient" in patch
    assert "Implementation diff" in provider.requests[0].prompt
    assert "pytest" in provider.requests[0].system_prompt.lower()


def test_tester_agent_rejects_non_patch_output() -> None:
    provider = FakeLLMProvider(responses=["Add a test file for the ping endpoint."])
    tester = DevTeamTesterAgent(provider)

    with pytest.raises(AgentOutputError, match="did not contain a unified diff"):
        tester.generate_test_patch(
            user_request="Add tests for the /ping endpoint.",
            task_list=make_task_list(),
            architecture_plan=make_architecture_plan(),
            relevant_files=[],
        )


def test_tester_agent_can_add_tests_to_demo_app(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    demo_source = project_root / "examples" / "fastapi-demo-app"
    demo_repo = tmp_path / "fastapi-demo-app"
    shutil.copytree(demo_source, demo_repo)

    tester = DevTeamTesterAgent(FakeLLMProvider(responses=[demo_test_patch()]))
    patch = tester.generate_test_patch(
        user_request="Add tests for the /ping endpoint.",
        task_list=make_task_list(),
        architecture_plan=make_architecture_plan(),
        relevant_files=[
            RelevantFile(
                path="app/main.py",
                content=(demo_repo / "app" / "main.py").read_text(encoding="utf-8"),
            )
        ],
    )

    apply_unified_diff(demo_repo, patch)
    result = run_pytest(demo_repo, args=["-q", "tests/test_app.py"], timeout_seconds=10)

    assert result.success is True
    assert result.passed_count == 1


def demo_test_patch() -> str:
    return (
        "diff --git a/tests/test_app.py b/tests/test_app.py\n"
        "--- /dev/null\n"
        "+++ b/tests/test_app.py\n"
        "@@ -0,0 +1,9 @@\n"
        "+from fastapi.testclient import TestClient\n"
        "+\n"
        "+from app.main import app\n"
        "+\n"
        "+\n"
        "+def test_ping_returns_pong() -> None:\n"
        "+    client = TestClient(app)\n"
        '+    response = client.get("/ping")\n'
        '+    assert response.json() == {"message": "pong"}\n'
    )
