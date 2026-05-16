"""Tests for Phase 7 static-analysis quality gate tools."""

from pathlib import Path

import pytest

import app.tools.static_analysis as static_analysis
from app.schemas.agent_state import StaticAnalysisResult
from app.schemas.agent_state import TestResult as AgentTestResult
from app.tools import (
    QualityGateResult,
    parse_static_analysis_output,
    run_static_analysis_command,
)


def make_test_result(success: bool = True) -> AgentTestResult:
    return AgentTestResult(
        command="pytest",
        success=success,
        passed_count=1 if success else 0,
        failed_count=0 if success else 1,
    )


def make_static_result(
    tool: str, success: bool = True, skipped: bool = False
) -> StaticAnalysisResult:
    return StaticAnalysisResult(
        tool=tool,
        command=f"{tool} command",
        success=success,
        skipped=skipped,
        issues=[] if success else [f"{tool} failed"],
    )


def test_parse_static_analysis_output_success_has_no_issues() -> None:
    result = parse_static_analysis_output(
        tool="ruff",
        command="ruff check .",
        return_code=0,
        stdout="All checks passed!\n",
        stderr="",
        duration_seconds=0.1,
    )

    assert result.success is True
    assert result.issues == []
    assert result.output == "All checks passed!\n"


def test_parse_static_analysis_output_extracts_readable_failure_lines() -> None:
    result = parse_static_analysis_output(
        tool="mypy",
        command="mypy app",
        return_code=1,
        stdout="app/main.py:10: error: Incompatible return value type\nFound 1 error\n",
        stderr="",
        duration_seconds=0.2,
    )

    assert result.success is False
    assert result.issues == ["app/main.py:10: error: Incompatible return value type"]


def test_missing_static_analysis_tool_is_reported_as_skipped(tmp_path: Path) -> None:
    result = run_static_analysis_command(
        tmp_path,
        tool="missing-tool",
        command=["definitely-not-a-real-devteam-ai-tool", "--version"],
    )

    assert result.success is True
    assert result.skipped is True
    assert "not installed" in result.output


def test_quality_gate_result_ignores_skipped_tools_for_pass_status() -> None:
    result = QualityGateResult(
        test_result=make_test_result(success=True),
        static_analysis_results=[
            make_static_result("ruff", success=True),
            make_static_result("semgrep", success=True, skipped=True),
        ],
    )

    assert result.all_passed is True
    assert result.missing_tools == ["semgrep"]


def test_quality_gate_result_fails_when_tests_fail() -> None:
    result = QualityGateResult(
        test_result=make_test_result(success=False),
        static_analysis_results=[make_static_result("ruff", success=True)],
    )

    assert result.all_passed is False


def test_quality_gate_result_fails_when_static_analysis_fails() -> None:
    result = QualityGateResult(
        test_result=make_test_result(success=True),
        static_analysis_results=[make_static_result("ruff", success=False)],
    )

    assert result.all_passed is False


def test_run_all_quality_gates_uses_expected_tool_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_run_pytest(repo_path: str | Path, *, timeout_seconds: float) -> AgentTestResult:
        calls.append(f"pytest:{timeout_seconds}")
        return make_test_result(success=True)

    def fake_static(tool: str):
        def runner(repo_path: str | Path, *, timeout_seconds: float) -> StaticAnalysisResult:
            calls.append(f"{tool}:{timeout_seconds}")
            return make_static_result(tool, success=True)

        return runner

    monkeypatch.setattr(static_analysis, "run_pytest", fake_run_pytest)
    monkeypatch.setattr(static_analysis, "run_ruff_check", fake_static("ruff"))
    monkeypatch.setattr(static_analysis, "run_ruff_format_check", fake_static("ruff-format"))
    monkeypatch.setattr(static_analysis, "run_mypy", fake_static("mypy"))
    monkeypatch.setattr(static_analysis, "run_bandit", fake_static("bandit"))
    monkeypatch.setattr(static_analysis, "run_semgrep", fake_static("semgrep"))

    result = static_analysis.run_all_quality_gates(
        Path("."),
        include_semgrep=True,
        pytest_timeout_seconds=3,
        static_timeout_seconds=4,
    )

    assert result.all_passed is True
    assert calls == [
        "pytest:3",
        "ruff:4",
        "ruff-format:4",
        "mypy:4",
        "bandit:4",
        "semgrep:4",
    ]
