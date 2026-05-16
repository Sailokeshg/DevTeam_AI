"""Pytest runner and result parsing tools."""

import re
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

from app.schemas.agent_state import TestResult
from app.tools.file_tools import FileToolError, resolve_repo_path

SUMMARY_PATTERN = re.compile(
    r"(?P<count>\d+)\s+"
    r"(?P<kind>passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b"
)
FAILED_TEST_PATTERN = re.compile(r"^(?:FAILED|ERROR)\s+(?P<name>\S+)", re.MULTILINE)


class TestRunnerError(ValueError):
    """Raised when pytest cannot be started or parsed."""


def run_pytest(
    repo_path: str | Path,
    *,
    args: list[str] | None = None,
    timeout_seconds: float = 30,
) -> TestResult:
    """Run pytest in a repository and return structured results."""
    if timeout_seconds <= 0:
        raise TestRunnerError("timeout_seconds must be greater than 0")

    repo_root = resolve_repo_path(repo_path)
    pytest_args = args if args is not None else ["-q"]
    command = [sys.executable, "-m", "pytest", *pytest_args]
    start_time = time.monotonic()

    try:
        result = subprocess.run(  # nosec B603
            command,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start_time
        stdout = _coerce_output(exc.stdout)
        stderr = _coerce_output(exc.stderr)
        timeout_message = f"pytest timed out after {timeout_seconds} seconds"
        error_output = "\n".join(part for part in [timeout_message, stderr] if part)
        return TestResult(
            command=_command_to_string(command),
            success=False,
            passed_count=0,
            failed_count=1,
            skipped_count=0,
            output=stdout,
            error_output=error_output,
            duration_seconds=duration,
        )
    except (OSError, FileToolError) as exc:
        raise TestRunnerError(f"Unable to run pytest: {exc}") from exc

    duration = time.monotonic() - start_time
    return parse_pytest_output(
        command=command,
        return_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_seconds=duration,
    )


def parse_pytest_output(
    *,
    command: list[str],
    return_code: int,
    stdout: str,
    stderr: str,
    duration_seconds: float | None = None,
) -> TestResult:
    """Parse pytest output into the shared `TestResult` schema."""
    combined_output = "\n".join(part for part in [stdout, stderr] if part)
    counts = _parse_summary_counts(combined_output)
    failed_tests = FAILED_TEST_PATTERN.findall(combined_output)
    failed_count = counts["failed"] + counts["error"]

    if return_code != 0 and failed_count == 0:
        failed_count = 1

    return TestResult(
        command=_command_to_string(command),
        success=return_code == 0,
        passed_count=counts["passed"],
        failed_count=failed_count,
        skipped_count=counts["skipped"],
        failed_tests=failed_tests,
        output=stdout,
        error_output=stderr,
        duration_seconds=duration_seconds,
    )


def _parse_summary_counts(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}

    for match in SUMMARY_PATTERN.finditer(output):
        kind = match.group("kind")
        count = int(match.group("count"))

        if kind == "passed":
            counts["passed"] += count
        elif kind == "failed":
            counts["failed"] += count
        elif kind in {"error", "errors"}:
            counts["error"] += count
        elif kind == "skipped":
            counts["skipped"] += count

    return counts


def _command_to_string(command: list[str]) -> str:
    return " ".join(command)


def _coerce_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output
