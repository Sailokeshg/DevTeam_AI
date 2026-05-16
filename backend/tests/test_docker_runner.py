"""Tests for Phase 12 Docker sandbox command validation."""

import subprocess
from pathlib import Path

import pytest

from app.tools.docker_runner import (
    DockerCommandValidationError,
    DockerRunnerError,
    DockerSandboxConfig,
    build_docker_command,
    run_sandboxed_command,
    validate_sandbox_command,
)


def test_validate_sandbox_command_accepts_allowlisted_commands() -> None:
    assert validate_sandbox_command(["pytest", "-q"]) == ["pytest", "-q"]
    assert validate_sandbox_command("ruff format --check .") == [
        "ruff",
        "format",
        "--check",
        ".",
    ]
    assert validate_sandbox_command(["semgrep", "scan", "--config", "auto"]) == [
        "semgrep",
        "scan",
        "--config",
        "auto",
    ]


@pytest.mark.parametrize(
    "command",
    [
        ["rm", "-rf", "."],
        ["python", "-c", "print('unsafe')"],
        ["bash", "-lc", "pytest"],
        ["docker", "ps"],
    ],
)
def test_validate_sandbox_command_blocks_unlisted_executables(command: list[str]) -> None:
    with pytest.raises(DockerCommandValidationError, match="not allowed"):
        validate_sandbox_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q ; rm -rf .",
        ["pytest", "tests", "&&", "rm", "-rf", "."],
        ["pytest", ".."],
        ["ruff", "check", "../outside"],
        ["semgrep", "scan", "--config=../rules.yml"],
        ["mypy", "/tmp/outside"],
        ["bandit", "-c=/tmp/bandit.yml", "-r", "app"],
    ],
)
def test_validate_sandbox_command_rejects_shell_or_escape_tokens(
    command: str | list[str],
) -> None:
    with pytest.raises(DockerCommandValidationError):
        validate_sandbox_command(command)


def test_build_docker_command_adds_resource_limits_and_safe_mount(tmp_path: Path) -> None:
    config = DockerSandboxConfig(
        image="devteam-ai-sandbox:test",
        timeout_seconds=20,
        memory_limit="256m",
        cpus=0.5,
        pids_limit=64,
        network_disabled=True,
        repository_read_only=True,
    )

    docker_command = build_docker_command(tmp_path, ["pytest", "-q"], config=config)

    assert docker_command[:2] == ["docker", "run"]
    assert "--rm" in docker_command
    assert ["--memory", "256m"] == _option_pair(docker_command, "--memory")
    assert ["--cpus", "0.5"] == _option_pair(docker_command, "--cpus")
    assert ["--pids-limit", "64"] == _option_pair(docker_command, "--pids-limit")
    assert ["--network", "none"] == _option_pair(docker_command, "--network")
    assert "--read-only" in docker_command
    assert "--cap-drop" in docker_command
    assert f"{tmp_path.resolve()}:/workspace:ro" in docker_command
    assert docker_command[-3:] == ["devteam-ai-sandbox:test", "pytest", "-q"]


def test_build_docker_command_can_keep_network_enabled(tmp_path: Path) -> None:
    docker_command = build_docker_command(
        tmp_path,
        ["bandit", "-r", "app"],
        config=DockerSandboxConfig(network_disabled=False),
    )

    assert "--network" not in docker_command
    assert f"{tmp_path.resolve()}:/workspace:rw" in docker_command


def test_docker_sandbox_config_validates_limits() -> None:
    with pytest.raises(DockerRunnerError, match="timeout_seconds"):
        DockerSandboxConfig(timeout_seconds=0)
    with pytest.raises(DockerRunnerError, match="pids_limit"):
        DockerSandboxConfig(pids_limit=4)


def test_run_sandboxed_command_reports_missing_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.tools.docker_runner.shutil.which", lambda executable: None)

    with pytest.raises(DockerRunnerError, match="Docker CLI"):
        run_sandboxed_command(tmp_path, ["pytest", "-q"])


def test_run_sandboxed_command_normalizes_completed_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="1 passed",
            stderr="",
        )

    monkeypatch.setattr(
        "app.tools.docker_runner.shutil.which", lambda executable: "/usr/bin/docker"
    )
    monkeypatch.setattr("app.tools.docker_runner.subprocess.run", fake_run)

    result = run_sandboxed_command(tmp_path, ["pytest", "-q"])

    assert result.success is True
    assert result.return_code == 0
    assert result.command == "pytest -q"
    assert result.output == "1 passed"
    assert result.docker_command[0] == "/usr/bin/docker"


def _option_pair(command: list[str], option: str) -> list[str]:
    option_index = command.index(option)
    return command[option_index : option_index + 2]
