"""Validation tests for Phase 1 shared schemas."""

import pytest
from pydantic import ValidationError

from app.schemas import (
    AgentState,
    ArchitecturePlan,
    CodeChange,
    ReviewIssue,
    ReviewResult,
    StaticAnalysisResult,
    Task,
    TaskList,
)
from app.schemas import (
    TestResult as AgentTestResult,
)


def make_task(task_id: str, dependencies: list[str] | None = None) -> Task:
    """Create a valid task for schema tests."""
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        description="Implement a focused piece of backend behavior.",
        type="feature",
        dependencies=dependencies or [],
        acceptance_criteria=["The task has observable, tested behavior."],
    )


def test_task_list_accepts_valid_dependency_graph() -> None:
    task_list = TaskList(
        tasks=[
            make_task("task-1"),
            make_task("task-2", dependencies=["task-1"]),
            make_task("task-3", dependencies=["task-2"]),
        ]
    )

    assert [task.id for task in task_list.tasks] == ["task-1", "task-2", "task-3"]


def test_task_list_rejects_duplicate_task_ids() -> None:
    with pytest.raises(ValidationError, match="Task ids must be unique"):
        TaskList(tasks=[make_task("task-1"), make_task("task-1")])


def test_task_list_rejects_unknown_dependencies() -> None:
    with pytest.raises(ValidationError, match="unknown dependencies"):
        TaskList(tasks=[make_task("task-1", dependencies=["missing-task"])])


def test_task_list_rejects_dependency_cycles() -> None:
    with pytest.raises(ValidationError, match="cannot contain cycles"):
        TaskList(
            tasks=[
                make_task("task-1", dependencies=["task-2"]),
                make_task("task-2", dependencies=["task-1"]),
            ]
        )


def test_review_issue_rejects_invalid_severity() -> None:
    with pytest.raises(ValidationError):
        ReviewIssue(severity="urgent", message="Invalid severity value")


def test_schema_models_reject_unexpected_fields() -> None:
    with pytest.raises(ValidationError):
        Task(
            id="task-1",
            title="Add endpoint",
            description="Add a backend endpoint.",
            type="feature",
            dependencies=[],
            acceptance_criteria=["Endpoint is tested."],
            owner="planner",
        )


def test_agent_state_can_represent_complete_multi_agent_run() -> None:
    task_list = TaskList(tasks=[make_task("task-1")])
    architecture_plan = ArchitecturePlan(
        summary="Add a new FastAPI route with focused tests.",
        impacted_files=["backend/app/api/routes.py", "backend/tests/test_health.py"],
        design_choices=["Keep route logic inside the existing API router."],
        risks=["Endpoint response contract must stay stable."],
        testing_strategy=["Use FastAPI TestClient for route coverage."],
    )
    code_change = CodeChange(
        file_path="backend/app/api/routes.py",
        change_type="modify",
        description="Add a new route handler.",
        diff="diff --git a/backend/app/api/routes.py b/backend/app/api/routes.py",
    )
    test_result = AgentTestResult(
        command="pytest",
        success=True,
        passed_count=3,
        failed_count=0,
        output="3 passed",
        duration_seconds=0.42,
    )
    lint_result = StaticAnalysisResult(
        tool="ruff",
        command="ruff check .",
        success=True,
        output="All checks passed!",
    )
    type_result = StaticAnalysisResult(
        tool="mypy",
        command="mypy app",
        success=True,
        output="Success: no issues found",
    )
    security_result = StaticAnalysisResult(
        tool="bandit",
        command="bandit -r app",
        success=True,
        output="No issues identified.",
    )
    review_result = ReviewResult(
        approved=True,
        issues=[],
        recommended_next_action="approve",
        summary="Implementation satisfies the request and quality checks passed.",
    )

    state = AgentState(
        user_request="Add a status endpoint.",
        repository_path="/tmp/example-repo",
        repository_summary="Small FastAPI service with route tests.",
        task_list=task_list,
        architecture_plan=architecture_plan,
        changed_files=["backend/app/api/routes.py", "backend/tests/test_health.py"],
        code_changes=[code_change],
        patch="diff --git a/backend/app/api/routes.py b/backend/app/api/routes.py",
        diff="diff --git a/backend/app/api/routes.py b/backend/app/api/routes.py",
        test_results=[test_result],
        lint_results=[lint_result],
        type_check_results=[type_result],
        security_results=[security_result],
        review_result=review_result,
        iteration_count=1,
        final_status="approved",
    )

    dumped_state = state.model_dump()

    assert dumped_state["final_status"] == "approved"
    assert dumped_state["task_list"]["tasks"][0]["id"] == "task-1"
    assert dumped_state["review_result"]["approved"] is True
