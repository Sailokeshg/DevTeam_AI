"""Tests for Phase 10 run-management API endpoints."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_run_store, get_workflow_runner
from app.main import app
from app.schemas.agent_state import (
    AgentState,
    ArchitecturePlan,
    StaticAnalysisResult,
)
from app.schemas.agent_state import (
    TestResult as AgentTestResult,
)
from app.schemas.review import ReviewResult
from app.schemas.task import TaskList
from app.storage import SQLiteRunStore


@pytest.fixture
def run_store(tmp_path: Path) -> SQLiteRunStore:
    return SQLiteRunStore(tmp_path / "runs.sqlite3")


@pytest.fixture
def client(run_store: SQLiteRunStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_run_store] = lambda: run_store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_completed_state(repo_path: str, feature_request: str) -> AgentState:
    task_list = TaskList.model_validate(
        {
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Add ping endpoint",
                    "description": "Implement and test a ping endpoint.",
                    "type": "feature",
                    "dependencies": [],
                    "acceptance_criteria": ["/ping returns pong."],
                }
            ]
        }
    )
    architecture_plan = ArchitecturePlan(
        summary="Add a small FastAPI route and pytest coverage.",
        impacted_files=["app/main.py", "tests/test_main.py"],
        design_choices=["Keep the route in the existing app module."],
        risks=["Route path could conflict with an existing endpoint."],
        testing_strategy=["Use TestClient to assert status and payload."],
    )

    return AgentState(
        user_request=feature_request,
        repository_path=repo_path,
        repository_summary="Demo FastAPI repository.",
        task_list=task_list,
        architecture_plan=architecture_plan,
        changed_files=["app/main.py", "tests/test_main.py"],
        patch="--- a/app/main.py\n+++ b/app/main.py",
        diff="diff --git a/app/main.py b/app/main.py",
        test_results=[
            AgentTestResult(
                command="pytest",
                success=True,
                passed_count=2,
                failed_count=0,
                output="2 passed",
            )
        ],
        lint_results=[
            StaticAnalysisResult(
                tool="ruff",
                command="ruff check .",
                success=True,
                output="All checks passed!",
            )
        ],
        review_result=ReviewResult(
            approved=True,
            issues=[],
            recommended_next_action="approve",
            summary="Approved after tests and lint passed.",
        ),
        iteration_count=1,
        final_status="approved",
    )


def run_fake_workflow(*, repo_path: str, feature_request: str, max_iterations: int) -> AgentState:
    return make_completed_state(repo_path, feature_request)


def test_create_run_executes_workflow_and_persists_state(
    client: TestClient,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_runner(*, repo_path: str, feature_request: str, max_iterations: int) -> AgentState:
        calls.append(
            {
                "repo_path": repo_path,
                "feature_request": feature_request,
                "max_iterations": max_iterations,
            }
        )
        return make_completed_state(repo_path, feature_request)

    app.dependency_overrides[get_workflow_runner] = lambda: fake_runner

    response = client.post(
        "/runs",
        json={
            "repository_path": str(tmp_path),
            "feature_request": "Add /ping endpoint.",
            "max_iterations": 2,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["run_id"]
    assert body["status"] == "approved"
    assert body["state"]["final_status"] == "approved"
    assert body["state"]["diff"] == "diff --git a/app/main.py b/app/main.py"
    assert calls == [
        {
            "repo_path": str(tmp_path),
            "feature_request": "Add /ping endpoint.",
            "max_iterations": 2,
        }
    ]

    saved_response = client.get(f"/runs/{body['run_id']}")

    assert saved_response.status_code == 200
    assert saved_response.json()["state"]["review_result"]["approved"] is True


def test_run_diff_endpoint_returns_final_diff(client: TestClient, tmp_path: Path) -> None:
    app.dependency_overrides[get_workflow_runner] = lambda: run_fake_workflow
    create_response = client.post(
        "/runs",
        json={"repository_path": str(tmp_path), "feature_request": "Add /ping endpoint."},
    )
    run_id = create_response.json()["run_id"]

    diff_response = client.get(f"/runs/{run_id}/diff")

    assert diff_response.status_code == 200
    assert diff_response.json() == {
        "run_id": run_id,
        "diff": "diff --git a/app/main.py b/app/main.py",
    }


def test_run_logs_endpoint_returns_agent_and_quality_logs(
    client: TestClient,
    tmp_path: Path,
) -> None:
    app.dependency_overrides[get_workflow_runner] = lambda: run_fake_workflow
    create_response = client.post(
        "/runs",
        json={"repository_path": str(tmp_path), "feature_request": "Add /ping endpoint."},
    )
    run_id = create_response.json()["run_id"]

    logs_response = client.get(f"/runs/{run_id}/logs")

    assert logs_response.status_code == 200
    sources = {entry["source"] for entry in logs_response.json()["logs"]}
    assert {"workflow", "planner", "architect", "coder", "pytest", "ruff", "reviewer"} <= sources


def test_run_endpoints_return_404_for_unknown_run(client: TestClient) -> None:
    response = client.get("/runs/not-a-real-run")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found: not-a-real-run"


def test_sqlite_run_store_round_trips_updated_state(
    run_store: SQLiteRunStore,
    tmp_path: Path,
) -> None:
    created = run_store.create_run(
        repository_path=str(tmp_path),
        feature_request="Add /ping endpoint.",
    )
    final_state = make_completed_state(str(tmp_path), "Add /ping endpoint.")

    updated = run_store.update_run_state(created.run_id, final_state)
    loaded = run_store.get_run(created.run_id)

    assert updated.status == "approved"
    assert loaded.status == "approved"
    assert loaded.state.diff == "diff --git a/app/main.py b/app/main.py"
    assert loaded.created_at == created.created_at
