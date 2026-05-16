"""Static analysis and quality gate runners."""

import shutil
import subprocess  # nosec B404
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_state import StaticAnalysisResult, TestResult
from app.tools.file_tools import FileToolError, resolve_repo_path
from app.tools.test_runner import run_pytest

DEFAULT_TIMEOUT_SECONDS = 60.0


class StaticAnalysisRunnerError(ValueError):
    """Raised when static analysis configuration is invalid."""


class QualityGateResult(BaseModel):
    """Combined pytest and static-analysis quality gate output."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    test_result: TestResult
    static_analysis_results: list[StaticAnalysisResult] = Field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        """Whether tests and non-skipped static-analysis tools passed."""
        return self.test_result.success and all(
            result.success for result in self.static_analysis_results if not result.skipped
        )

    @property
    def missing_tools(self) -> list[str]:
        """Tools that were skipped because they were not installed."""
        return [result.tool for result in self.static_analysis_results if result.skipped]


def run_ruff_check(
    repo_path: str | Path, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> StaticAnalysisResult:
    """Run Ruff lint checks."""
    return run_static_analysis_command(
        repo_path,
        tool="ruff",
        command=["ruff", "check", "."],
        timeout_seconds=timeout_seconds,
    )


def run_ruff_format_check(
    repo_path: str | Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> StaticAnalysisResult:
    """Run Ruff formatting checks without modifying files."""
    return run_static_analysis_command(
        repo_path,
        tool="ruff-format",
        command=["ruff", "format", "--check", "."],
        timeout_seconds=timeout_seconds,
    )


def run_mypy(
    repo_path: str | Path, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> StaticAnalysisResult:
    """Run mypy type checking."""
    return run_static_analysis_command(
        repo_path,
        tool="mypy",
        command=["mypy", "app"],
        timeout_seconds=timeout_seconds,
    )


def run_bandit(
    repo_path: str | Path, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> StaticAnalysisResult:
    """Run Bandit security scanning."""
    return run_static_analysis_command(
        repo_path,
        tool="bandit",
        command=["bandit", "-r", "app"],
        timeout_seconds=timeout_seconds,
    )


def run_semgrep(
    repo_path: str | Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> StaticAnalysisResult:
    """Run optional Semgrep Community Edition scanning when installed."""
    return run_static_analysis_command(
        repo_path,
        tool="semgrep",
        command=["semgrep", "scan", "--config", "auto"],
        timeout_seconds=timeout_seconds,
        optional=True,
    )


def run_all_quality_gates(
    repo_path: str | Path,
    *,
    include_semgrep: bool = False,
    pytest_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    static_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> QualityGateResult:
    """Run pytest plus all configured static-analysis quality gates."""
    test_result = run_pytest(repo_path, timeout_seconds=pytest_timeout_seconds)
    static_results = [
        run_ruff_check(repo_path, timeout_seconds=static_timeout_seconds),
        run_ruff_format_check(repo_path, timeout_seconds=static_timeout_seconds),
        run_mypy(repo_path, timeout_seconds=static_timeout_seconds),
        run_bandit(repo_path, timeout_seconds=static_timeout_seconds),
    ]

    if include_semgrep:
        static_results.append(run_semgrep(repo_path, timeout_seconds=static_timeout_seconds))

    return QualityGateResult(test_result=test_result, static_analysis_results=static_results)


def run_static_analysis_command(
    repo_path: str | Path,
    *,
    tool: str,
    command: list[str],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    optional: bool = False,
) -> StaticAnalysisResult:
    """Run a static-analysis command and normalize its output."""
    if not command:
        raise StaticAnalysisRunnerError("Static-analysis command cannot be empty")
    if timeout_seconds <= 0:
        raise StaticAnalysisRunnerError("timeout_seconds must be greater than 0")

    executable = command[0]
    executable_path = shutil.which(executable)
    command_string = _command_to_string(command)

    if executable_path is None:
        label = "optional " if optional else ""
        message = f"{label}tool `{executable}` is not installed; skipped."
        return StaticAnalysisResult(
            tool=tool,
            command=command_string,
            success=True,
            skipped=True,
            issues=[message],
            output=message,
        )

    try:
        repo_root = resolve_repo_path(repo_path)
    except FileToolError as exc:
        raise StaticAnalysisRunnerError(f"Invalid repository path: {exc}") from exc

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
        timeout_message = f"{tool} timed out after {timeout_seconds} seconds"
        stderr = _coerce_output(exc.stderr)
        return StaticAnalysisResult(
            tool=tool,
            command=command_string,
            success=False,
            issues=[timeout_message],
            output=_coerce_output(exc.stdout),
            error_output="\n".join(part for part in [timeout_message, stderr] if part),
            duration_seconds=duration,
        )
    except OSError as exc:
        raise StaticAnalysisRunnerError(f"Unable to run {tool}: {exc}") from exc

    duration = time.monotonic() - start_time
    return parse_static_analysis_output(
        tool=tool,
        command=command_string,
        return_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_seconds=duration,
    )


def parse_static_analysis_output(
    *,
    tool: str,
    command: str,
    return_code: int,
    stdout: str,
    stderr: str,
    duration_seconds: float | None = None,
) -> StaticAnalysisResult:
    """Parse a static-analysis command result into the shared schema."""
    output = stdout or ""
    error_output = stderr or ""
    success = return_code == 0
    combined_output = "\n".join(part for part in [output, error_output] if part)
    issues = [] if success else _extract_issue_lines(combined_output)

    if not success and not issues:
        issues = [f"{tool} failed with exit code {return_code}"]

    return StaticAnalysisResult(
        tool=tool,
        command=command,
        success=success,
        issues=issues,
        output=output,
        error_output=error_output,
        duration_seconds=duration_seconds,
    )


def _extract_issue_lines(output: str) -> list[str]:
    ignored_prefixes = (
        "Found ",
        "would reformat",
        "Oh no!",
        "Success:",
    )
    issues: list[str] = []

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(ignored_prefixes):
            continue
        issues.append(line)

    return issues


def _command_to_string(command: list[str]) -> str:
    return " ".join(command)


def _coerce_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output
