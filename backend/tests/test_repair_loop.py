"""Tests for the Phase 8 manual repair loop."""

from pathlib import Path

import pytest

from app.graph.workflow import RepairLoopError, build_repair_feedback, run_repair_loop
from app.schemas.agent_state import (
    AgentState,
    ArchitecturePlan,
    StaticAnalysisResult,
)
from app.schemas.agent_state import (
    TestResult as AgentTestResult,
)
from app.schemas.review import ReviewIssue, ReviewResult
from app.tools.static_analysis import QualityGateResult


def make_state() -> AgentState:
    return AgentState(
        user_request="Add tests for /ping.",
        repository_path=str(Path("/tmp/demo-repo")),
        architecture_plan=ArchitecturePlan(
            summary="Add tests with FastAPI TestClient.",
            impacted_files=["tests/test_app.py"],
            design_choices=["Keep endpoint tests local."],
            risks=["Test imports must resolve from repo root."],
            testing_strategy=["Assert status code and response body."],
        ),
        diff="diff --git a/tests/test_app.py b/tests/test_app.py",
    )


def make_test_result(success: bool = True) -> AgentTestResult:
    return AgentTestResult(
        command="pytest",
        success=success,
        passed_count=1 if success else 0,
        failed_count=0 if success else 1,
        failed_tests=[] if success else ["tests/test_app.py::test_ping"],
        error_output="" if success else "AssertionError: expected pong",
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


def make_review_result(
    *,
    approved: bool,
    action: str,
    issues: list[ReviewIssue] | None = None,
) -> ReviewResult:
    return ReviewResult(
        approved=approved,
        issues=issues or [],
        recommended_next_action=action,
        summary="review summary",
    )


def test_repair_loop_approves_passing_changes() -> None:
    coder_calls: list[str] = []
    tester_calls: list[str] = []

    result = run_repair_loop(
        make_state(),
        quality_gate_runner=lambda state: make_quality_result(tests_success=True),
        reviewer=lambda state: make_review_result(approved=True, action="approve"),
        coder_repair=lambda state, feedback: _record_and_return(state, feedback, coder_calls),
        tester_repair=lambda state, feedback: _record_and_return(state, feedback, tester_calls),
        max_iterations=3,
    )

    assert result.final_status == "approved"
    assert result.iteration_count == 1
    assert coder_calls == []
    assert tester_calls == []


def test_repair_loop_rejects_when_reviewer_recommends_stop() -> None:
    result = run_repair_loop(
        make_state(),
        quality_gate_runner=lambda state: make_quality_result(tests_success=True),
        reviewer=lambda state: make_review_result(
            approved=False,
            action="stop",
            issues=[ReviewIssue(severity="critical", message="Unsafe generated behavior")],
        ),
        coder_repair=lambda state, feedback: state,
        tester_repair=lambda state, feedback: state,
    )

    assert result.final_status == "rejected"
    assert result.review_result is not None
    assert result.review_result.recommended_next_action == "stop"


def test_repair_loop_routes_test_failures_to_tester_then_approves() -> None:
    quality_results = [
        make_quality_result(tests_success=False),
        make_quality_result(tests_success=True),
    ]
    review_results = [
        make_review_result(approved=False, action="revise_tests"),
        make_review_result(approved=True, action="approve"),
    ]
    tester_feedback: list[str] = []

    result = run_repair_loop(
        make_state(),
        quality_gate_runner=lambda state: quality_results.pop(0),
        reviewer=lambda state: review_results.pop(0),
        coder_repair=lambda state, feedback: state,
        tester_repair=lambda state, feedback: _record_and_return(state, feedback, tester_feedback),
        max_iterations=3,
    )

    assert result.final_status == "approved"
    assert result.iteration_count == 2
    assert len(tester_feedback) == 1
    assert "Test failures" in tester_feedback[0]


def test_repair_loop_routes_static_failures_to_coder() -> None:
    ruff_failure = StaticAnalysisResult(
        tool="ruff",
        command="ruff check .",
        success=False,
        issues=["app/main.py:1:1: F401 unused import"],
    )
    quality_results = [
        make_quality_result(tests_success=True, static_results=[ruff_failure]),
        make_quality_result(tests_success=True),
    ]
    review_results = [
        make_review_result(approved=False, action="revise_code"),
        make_review_result(approved=True, action="approve"),
    ]
    coder_feedback: list[str] = []

    result = run_repair_loop(
        make_state(),
        quality_gate_runner=lambda state: quality_results.pop(0),
        reviewer=lambda state: review_results.pop(0),
        coder_repair=lambda state, feedback: _record_and_return(state, feedback, coder_feedback),
        tester_repair=lambda state, feedback: state,
        max_iterations=3,
    )

    assert result.final_status == "approved"
    assert len(coder_feedback) == 1
    assert "Static-analysis failures" in coder_feedback[0]


def test_repair_loop_stops_after_max_iterations() -> None:
    tester_feedback: list[str] = []

    result = run_repair_loop(
        make_state(),
        quality_gate_runner=lambda state: make_quality_result(tests_success=False),
        reviewer=lambda state: make_review_result(approved=False, action="revise_tests"),
        coder_repair=lambda state, feedback: state,
        tester_repair=lambda state, feedback: _record_and_return(state, feedback, tester_feedback),
        max_iterations=2,
    )

    assert result.final_status == "max_iterations"
    assert result.iteration_count == 2
    assert len(tester_feedback) == 1


def test_repair_loop_rejects_invalid_iteration_limit() -> None:
    with pytest.raises(RepairLoopError, match="max_iterations"):
        run_repair_loop(
            make_state(),
            quality_gate_runner=lambda state: make_quality_result(),
            reviewer=lambda state: make_review_result(approved=True, action="approve"),
            coder_repair=lambda state, feedback: state,
            tester_repair=lambda state, feedback: state,
            max_iterations=0,
        )


def test_build_repair_feedback_includes_review_and_quality_details() -> None:
    state = make_state()
    state.review_result = make_review_result(
        approved=False,
        action="revise_code",
        issues=[
            ReviewIssue(
                severity="high",
                message="Fix unsafe input handling",
                file_path="app/main.py",
                line=4,
                suggested_fix="Validate input before use",
                source="reviewer",
            )
        ],
    )
    state.test_results = [make_test_result(success=False)]
    state.lint_results = [
        StaticAnalysisResult(
            tool="ruff",
            command="ruff check .",
            success=False,
            issues=["app/main.py:1:1: F401 unused import"],
        )
    ]

    feedback = build_repair_feedback(state)

    assert "Review summary" in feedback
    assert "Fix unsafe input handling" in feedback
    assert "Test failures" in feedback
    assert "Static-analysis failures" in feedback


def _record_and_return(state: AgentState, feedback: str, calls: list[str]) -> AgentState:
    calls.append(feedback)
    return state
