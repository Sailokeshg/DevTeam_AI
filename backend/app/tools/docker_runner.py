"""Docker sandbox runner for test and quality-gate commands."""

import shlex
import shutil
import subprocess  # nosec B404
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.tools.file_tools import FileToolError, resolve_repo_path

DEFAULT_SANDBOX_IMAGE = "devteam-ai-sandbox:latest"
ALLOWED_SANDBOX_EXECUTABLES = frozenset({"pytest", "ruff", "mypy", "bandit", "semgrep"})
FORBIDDEN_TOKEN_FRAGMENTS = frozenset({";", "&&", "||", "|", "`", "$(", ">", "<", "\n"})
CONTAINER_TMP_DIR = "/" + "tmp"


class DockerRunnerError(ValueError):
    """Raised when Docker sandbox execution cannot be started safely."""


class DockerCommandValidationError(DockerRunnerError):
    """Raised when a requested sandbox command is not allowed."""


@dataclass(frozen=True, slots=True)
class DockerSandboxConfig:
    """Configuration for constrained Docker command execution."""

    image: str = DEFAULT_SANDBOX_IMAGE
    timeout_seconds: float = 60.0
    memory_limit: str = "512m"
    cpus: float = 1.0
    pids_limit: int = 256
    network_disabled: bool = True
    repository_read_only: bool = False
    tmpfs_size: str = "256m"

    def __post_init__(self) -> None:
        if not self.image.strip():
            raise DockerRunnerError("Docker image cannot be empty")
        if self.timeout_seconds <= 0:
            raise DockerRunnerError("timeout_seconds must be greater than 0")
        if not self.memory_limit.strip():
            raise DockerRunnerError("memory_limit cannot be empty")
        if self.cpus <= 0:
            raise DockerRunnerError("cpus must be greater than 0")
        if self.pids_limit < 16:
            raise DockerRunnerError("pids_limit must be at least 16")
        if not self.tmpfs_size.strip():
            raise DockerRunnerError("tmpfs_size cannot be empty")


class DockerCommandResult(BaseModel):
    """Normalized result from a sandboxed Docker command."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    command: str
    docker_command: list[str]
    success: bool
    return_code: int | None
    timed_out: bool = False
    output: str = ""
    error_output: str = ""
    duration_seconds: float | None = Field(default=None, ge=0)


def validate_sandbox_command(command: Sequence[str] | str) -> list[str]:
    """Validate and normalize a command against the sandbox allowlist."""
    command_parts = _normalize_command(command)
    executable = command_parts[0]

    if executable not in ALLOWED_SANDBOX_EXECUTABLES:
        allowed = ", ".join(sorted(ALLOWED_SANDBOX_EXECUTABLES))
        raise DockerCommandValidationError(
            f"Command `{executable}` is not allowed in the sandbox. Allowed commands: {allowed}"
        )

    if "/" in executable or executable in {".", ".."}:
        raise DockerCommandValidationError(
            "Sandbox command must use an allowlisted executable name"
        )

    for token in command_parts:
        _validate_token(token)

    return command_parts


def build_docker_command(
    repo_path: str | Path,
    command: Sequence[str] | str,
    *,
    config: DockerSandboxConfig | None = None,
) -> list[str]:
    """Build the `docker run` invocation for a validated sandbox command."""
    active_config = config or DockerSandboxConfig()
    command_parts = validate_sandbox_command(command)
    repo_root = _resolve_repository(repo_path)
    mount_mode = "ro" if active_config.repository_read_only else "rw"

    docker_command = [
        "docker",
        "run",
        "--rm",
        "--workdir",
        "/workspace",
        "--memory",
        active_config.memory_limit,
        "--cpus",
        str(active_config.cpus),
        "--pids-limit",
        str(active_config.pids_limit),
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--read-only",
        "--tmpfs",
        f"{CONTAINER_TMP_DIR}:rw,noexec,nosuid,size={active_config.tmpfs_size}",
        "--tmpfs",
        "/home/sandbox:rw,nosuid,size=64m",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        f"RUFF_CACHE_DIR={CONTAINER_TMP_DIR}/ruff-cache",
        "--env",
        f"MYPY_CACHE_DIR={CONTAINER_TMP_DIR}/mypy-cache",
        "--volume",
        f"{repo_root}:/workspace:{mount_mode}",
        "--stop-timeout",
        "5",
    ]

    if active_config.network_disabled:
        docker_command.extend(["--network", "none"])

    docker_command.append(active_config.image)
    docker_command.extend(command_parts)
    return docker_command


def run_sandboxed_command(
    repo_path: str | Path,
    command: Sequence[str] | str,
    *,
    config: DockerSandboxConfig | None = None,
) -> DockerCommandResult:
    """Run an allowlisted command inside a constrained Docker container."""
    active_config = config or DockerSandboxConfig()
    docker_executable = shutil.which("docker")
    if docker_executable is None:
        raise DockerRunnerError("Docker CLI is not installed or not available on PATH")

    docker_command = build_docker_command(repo_path, command, config=active_config)
    docker_command[0] = docker_executable
    command_string = shlex.join(validate_sandbox_command(command))
    start_time = time.monotonic()

    try:
        result = subprocess.run(  # nosec B603
            docker_command,
            check=False,
            capture_output=True,
            text=True,
            timeout=active_config.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start_time
        timeout_message = f"Docker sandbox timed out after {active_config.timeout_seconds} seconds"
        stderr = _coerce_output(exc.stderr)
        return DockerCommandResult(
            command=command_string,
            docker_command=docker_command,
            success=False,
            return_code=None,
            timed_out=True,
            output=_coerce_output(exc.stdout),
            error_output="\n".join(part for part in [timeout_message, stderr] if part),
            duration_seconds=duration,
        )
    except OSError as exc:
        raise DockerRunnerError(f"Unable to run Docker sandbox: {exc}") from exc

    duration = time.monotonic() - start_time
    return DockerCommandResult(
        command=command_string,
        docker_command=docker_command,
        success=result.returncode == 0,
        return_code=result.returncode,
        output=result.stdout or "",
        error_output=result.stderr or "",
        duration_seconds=duration,
    )


def _normalize_command(command: Sequence[str] | str) -> list[str]:
    if isinstance(command, str):
        try:
            command_parts = shlex.split(command)
        except ValueError as exc:
            raise DockerCommandValidationError(f"Invalid command string: {exc}") from exc
    else:
        command_parts = list(command)

    if not command_parts:
        raise DockerCommandValidationError("Sandbox command cannot be empty")

    for token in command_parts:
        if not isinstance(token, str) or token == "":  # nosec B105
            raise DockerCommandValidationError("Sandbox command tokens must be non-empty strings")

    return command_parts


def _validate_token(token: str) -> None:
    if token == ".":  # nosec B105
        return

    if (
        token == ".."  # nosec B105
        or token.startswith("../")
        or "=../" in token
        or token.endswith("=..")
        or "/../" in token
        or token.endswith("/..")
    ):
        raise DockerCommandValidationError(
            "Sandbox command cannot reference paths outside /workspace"
        )

    if any(fragment in token for fragment in FORBIDDEN_TOKEN_FRAGMENTS):
        raise DockerCommandValidationError("Sandbox command cannot contain shell control operators")

    if token.startswith("/") or "=/" in token:
        raise DockerCommandValidationError(
            "Sandbox command arguments must use repository-relative paths"
        )


def _resolve_repository(repo_path: str | Path) -> Path:
    try:
        return resolve_repo_path(repo_path)
    except FileToolError as exc:
        raise DockerRunnerError(f"Invalid repository path: {exc}") from exc


def _coerce_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output
