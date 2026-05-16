"""Tests for Phase 6 pytest runner and parser."""

from pathlib import Path

from app.tools import parse_pytest_output, run_pytest


def test_parse_pytest_output_extracts_counts_and_failed_names() -> None:
    stdout = (
        "FAILED tests/test_app.py::test_bad - AssertionError\n"
        "ERROR tests/test_app.py::test_error - RuntimeError\n"
        "2 failed, 3 passed, 1 skipped, 1 error in 0.12s\n"
    )

    result = parse_pytest_output(
        command=["python", "-m", "pytest", "-q"],
        return_code=1,
        stdout=stdout,
        stderr="",
        duration_seconds=0.12,
    )

    assert result.success is False
    assert result.passed_count == 3
    assert result.failed_count == 3
    assert result.skipped_count == 1
    assert result.failed_tests == [
        "tests/test_app.py::test_bad",
        "tests/test_app.py::test_error",
    ]


def test_run_pytest_executes_passing_tests(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text(
        "def test_sample() -> None:\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )

    result = run_pytest(tmp_path, timeout_seconds=10)

    assert result.success is True
    assert result.passed_count == 1
    assert result.failed_count == 0


def test_run_pytest_captures_failing_tests(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text(
        "def test_sample_failure() -> None:\n    assert False\n",
        encoding="utf-8",
    )

    result = run_pytest(tmp_path, timeout_seconds=10)

    assert result.success is False
    assert result.failed_count == 1
    assert result.failed_tests == ["tests/test_sample.py::test_sample_failure"]


def test_run_pytest_reports_timeout(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_timeout.py").write_text(
        "import time\n\ndef test_timeout() -> None:\n    time.sleep(5)\n",
        encoding="utf-8",
    )

    result = run_pytest(tmp_path, timeout_seconds=0.2)

    assert result.success is False
    assert result.failed_count == 1
    assert "timed out" in result.error_output
