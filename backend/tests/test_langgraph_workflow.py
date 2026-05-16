"""Tests for Phase 9 LangGraph workflow orchestration."""

from pathlib import Path

import pytest

from app.graph import (
    WorkflowExecutionError,
    WorkflowServices,
    build_devteam_workflow_graph,
    run_workflow_with_services,
)
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
from app.tools.static_analysis import QualityGateResult


def make_initial_state() -> AgentState:
    return AgentState(
        user_request="Add tests for /ping.",
        repository_path=str(Path("/tmp/demo-repo")),
    )


def make_task_list() -> TaskList:
    return TaskList.model_validate(
        {
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Add ping tests",
                    "description": "Add pytest coverage for /ping.",
                    "type": "test",
                    "dependencies": [],
                    "acceptance_criteria": ["pytest covers /ping."],
                }
            ]
        }
    )


def make_architecture_plan() -> ArchitecturePlan:
    return ArchitecturePlan(
        summary="Use FastAPI TestClient.",
        impacted_files=["tests/test_app.py"],
        design_choices=["Keep tests local."],
        risks=["Imports must resolve."],
        testing_strategy=["Assert response body."],
    )


def make_test_result(success: bool = True) -> AgentTestResult:
    return AgentTestResult(
        command="pytest",
        success=success,
        passed_count=1 if success else 0,
        failed_count=0 if success else 1,
        failed_tests=[] if success else ["tests/test_app.py::test_ping"],
        error_output="" if success else "AssertionError",
    )


def make_quality_result(
    *,
    tests_success: bool = True,
    static_results: list[StaticAnalysisResult] | None = None,
) -> QualityGateResult:
    return QualityGateResult(
        test_result=make_test_result(success=tests_success),
        static_analysis_results=static_results or [],
    )


def make_review_result(*, approved: bool, action: str) -> ReviewResult:
    return ReviewResult(
        approved=approved,
        issues=[],
        recommended_next_action=action,
        summary="review summary",
    )


def make_base_services(
    *,
    quality_results: list[QualityGateResult] | None = None,
    review_results: list[ReviewResult] | None = None,
    coder_feedback: list[str] | None = None,
    tester_feedback: list[str] | None = None,
) -> WorkflowServices:
    quality_queue = quality_results or [make_quality_result(tests_success=True)]
    review_queue = review_results or [make_review_result(approved=True, action="approve")]
    coder_feedback = coder_feedback if coder_feedback is not None else []
    tester_feedback = tester_feedback if tester_feedback is not None else []

    def load_repo_context(state: AgentState) -> AgentState:
        state.repository_summary = "FastAPI demo app"
        return state

    def planner(state: AgentState) -> AgentState:
        state.task_list = make_task_list()
        return state

    def architect(state: AgentState) -> AgentState:
        state.architecture_plan = make_architecture_plan()
        return state

    def coder(state: AgentState, feedback: str) -> AgentState:
        coder_feedback.append(feedback)
        state.patch = "coder patch"
        state.diff = "coder diff"
        state.changed_files = ["app/main.py"]
        return state

    def tester(state: AgentState, feedback: str) -> AgentState:
        tester_feedback.append(feedback)
        state.patch = "tester patch"
        state.diff = "tester diff"
        state.changed_files = [*state.changed_files, "tests/test_app.py"]
        return state

    def quality_gate_runner(state: AgentState) -> QualityGateResult:
        return quality_queue.pop(0)

    def reviewer(state: AgentState) -> ReviewResult:
        return review_queue.pop(0)

    return WorkflowServices(
        load_repo_context=load_repo_context,
        planner=planner,
        architect=architect,
        coder=coder,
        tester=tester,
        quality_gate_runner=quality_gate_runner,
        reviewer=reviewer,
    )


def test_langgraph_workflow_runs_expected_agent_sequence() -> None:
    graph = build_devteam_workflow_graph(make_base_services())

    result = graph.invoke(
        {
            "agent_state": make_initial_state(),
            "max_iterations": 3,
            "quality_gate_passed": False,
            "workflow_events": [],
        }
    )
    final_state = AgentState.model_validate(result["agent_state"])

    assert result["workflow_events"] == [
        "load_repo_context",
        "planner",
        "architect",
        "coder",
        "tester",
        "run_quality_gates",
        "reviewer",
        "finalize",
    ]
    assert final_state.final_status == "approved"
    assert final_state.task_list is not None
    assert final_state.architecture_plan is not None


def test_langgraph_workflow_routes_test_failure_to_tester_repair() -> None:
    tester_feedback: list[str] = []
    services = make_base_services(
        quality_results=[
            make_quality_result(tests_success=False),
            make_quality_result(tests_success=True),
        ],
        review_results=[
            make_review_result(approved=False, action="revise_tests"),
            make_review_result(approved=True, action="approve"),
        ],
        tester_feedback=tester_feedback,
    )

    result = run_workflow_with_services(
        make_initial_state(),
        services=services,
        max_iterations=3,
    )

    assert result.final_status == "approved"
    assert result.iteration_count == 2
    assert len(tester_feedback) == 2
    assert tester_feedback[0] == ""
    assert "Test failures" in tester_feedback[1]


def test_langgraph_workflow_routes_static_failure_to_coder_repair() -> None:
    coder_feedback: list[str] = []
    ruff_failure = StaticAnalysisResult(
        tool="ruff",
        command="ruff check .",
        success=False,
        issues=["app/main.py:1:1: F401 unused import"],
    )
    services = make_base_services(
        quality_results=[
            make_quality_result(tests_success=True, static_results=[ruff_failure]),
            make_quality_result(tests_success=True),
        ],
        review_results=[
            make_review_result(approved=False, action="revise_code"),
            make_review_result(approved=True, action="approve"),
        ],
        coder_feedback=coder_feedback,
    )

    result = run_workflow_with_services(
        make_initial_state(),
        services=services,
        max_iterations=3,
    )

    assert result.final_status == "approved"
    assert result.iteration_count == 2
    assert len(coder_feedback) == 2
    assert coder_feedback[0] == ""
    assert "Static-analysis failures" in coder_feedback[1]


def test_langgraph_workflow_finalizes_at_max_iterations() -> None:
    services = make_base_services(
        quality_results=[make_quality_result(tests_success=False)],
        review_results=[make_review_result(approved=False, action="revise_tests")],
    )

    result = run_workflow_with_services(
        make_initial_state(),
        services=services,
        max_iterations=1,
    )

    assert result.final_status == "max_iterations"
    assert result.iteration_count == 1


def test_langgraph_workflow_rejects_invalid_iteration_limit() -> None:
    with pytest.raises(WorkflowExecutionError, match="max_iterations"):
        run_workflow_with_services(
            make_initial_state(),
            services=make_base_services(),
            max_iterations=0,
        )
