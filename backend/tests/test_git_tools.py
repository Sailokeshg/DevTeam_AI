"""Tests for Phase 13 Git and GitHub workflow helpers."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.tools.git_tools import (
    GitApprovalError,
    GitCommandError,
    GitHubConfigurationError,
    GitToolError,
    clone_public_repo,
    commit_changes,
    create_branch,
    create_github_pull_request,
    generate_pr_title_body,
    get_current_branch,
    get_git_diff,
    push_branch,
)


def run_git(repo_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )


def create_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    run_git(repo_path, "init")
    run_git(repo_path, "config", "user.name", "DevTeam AI Tests")
    run_git(repo_path, "config", "user.email", "devteam-ai@example.test")
    (repo_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    run_git(repo_path, "add", "README.md")
    run_git(repo_path, "commit", "-m", "initial commit")
    return repo_path


def test_clone_public_repo_supports_local_test_mirror(tmp_path: Path) -> None:
    source_repo = create_repo(tmp_path)
    clone_parent = tmp_path / "clones"

    result = clone_public_repo(source_repo, clone_parent, directory_name="copy")

    assert result.destination_path == clone_parent / "copy"
    assert (result.destination_path / "README.md").read_text(encoding="utf-8") == "# Demo\n"
    assert result.command[:2] == ["git", "clone"]


def test_create_branch_commit_changes_and_get_diff(tmp_path: Path) -> None:
    repo_path = create_repo(tmp_path)

    branch_result = create_branch(repo_path, "feature/ping")
    (repo_path / "README.md").write_text("# Demo\n\nAdds ping.\n", encoding="utf-8")
    diff = get_git_diff(repo_path)

    commit_result = commit_changes(
        repo_path,
        "Add ping docs",
        author_name="DevTeam AI Tests",
        author_email="devteam-ai@example.test",
    )

    assert branch_result.branch_name == "feature/ping"
    assert get_current_branch(repo_path) == "feature/ping"
    assert "Adds ping" in diff.diff
    assert diff.changed_files == ["README.md"]
    assert len(commit_result.commit_hash) == 40
    assert commit_result.changed_files == ["README.md"]
    assert get_git_diff(repo_path).diff == ""


def test_commit_changes_can_stage_selected_paths(tmp_path: Path) -> None:
    repo_path = create_repo(tmp_path)
    (repo_path / "README.md").write_text("# Demo\n\nUpdated.\n", encoding="utf-8")
    (repo_path / "notes.md").write_text("Untracked notes.\n", encoding="utf-8")

    commit_result = commit_changes(repo_path, "Update readme", paths=["README.md"])
    untracked = run_git(repo_path, "status", "--short").stdout

    assert commit_result.changed_files == ["README.md"]
    assert "?? notes.md" in untracked


def test_commit_changes_rejects_empty_commit_by_default(tmp_path: Path) -> None:
    repo_path = create_repo(tmp_path)

    with pytest.raises(GitToolError, match="No staged changes"):
        commit_changes(repo_path, "No changes")


def test_git_helpers_reject_unsafe_branch_and_paths(tmp_path: Path) -> None:
    repo_path = create_repo(tmp_path)

    with pytest.raises(GitToolError, match="Invalid branch"):
        create_branch(repo_path, "../bad")

    with pytest.raises(GitToolError, match="inside the repository"):
        commit_changes(repo_path, "Bad path", paths=["../outside.txt"])


def test_generate_pr_title_body_is_deterministic() -> None:
    draft = generate_pr_title_body(
        "Add input validation to create-user endpoint.",
        changed_files=["app/main.py", "tests/test_main.py"],
        test_summary="pytest passed",
        quality_summary="ruff and mypy passed",
    )

    assert draft.title == "Implement Add input validation to create-user endpoint"
    assert "`app/main.py`" in draft.body
    assert "pytest passed" in draft.body
    assert "ruff and mypy passed" in draft.body


def test_push_branch_requires_explicit_approval(tmp_path: Path) -> None:
    repo_path = create_repo(tmp_path)

    with pytest.raises(GitApprovalError, match="approval"):
        push_branch(repo_path, branch_name="main")


def test_create_github_pull_request_requires_approval_before_configuration(
    tmp_path: Path,
) -> None:
    repo_path = create_repo(tmp_path)

    with pytest.raises(GitApprovalError, match="approval"):
        create_github_pull_request(
            repo_path,
            base_branch="main",
            head_branch="feature/ping",
            title="Add ping",
            body="## Summary\n- Add ping\n",
        )


def test_create_github_pull_request_requires_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = create_repo(tmp_path)
    monkeypatch.setattr("app.tools.git_tools.shutil.which", lambda executable: "/usr/bin/gh")
    monkeypatch.delenv("TEST_GITHUB_TOKEN", raising=False)

    with pytest.raises(GitHubConfigurationError, match="token"):
        create_github_pull_request(
            repo_path,
            base_branch="main",
            head_branch="feature/ping",
            title="Add ping",
            body="## Summary\n- Add ping\n",
            approved=True,
            token_env_vars=("TEST_GITHUB_TOKEN",),
        )


def test_create_github_pull_request_uses_gh_without_exposing_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = create_repo(tmp_path)
    captured_env: dict[str, str] = {}
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "secret-token")
    monkeypatch.setattr("app.tools.git_tools.shutil.which", lambda executable: "/usr/bin/gh")

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{repo_path}\n", stderr="")
        if command[:3] == ["/usr/bin/gh", "pr", "create"]:
            captured_env.update(env or {})
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="https://github.com/example/repo/pull/7\n",
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr("app.tools.git_tools.subprocess.run", fake_run)

    result = create_github_pull_request(
        repo_path,
        base_branch="main",
        head_branch="feature/ping",
        title="Add ping",
        body="## Summary\n- Add ping\n",
        approved=True,
        token_env_vars=("TEST_GITHUB_TOKEN",),
    )

    assert result.url == "https://github.com/example/repo/pull/7"
    assert captured_env["GH_TOKEN"] == "secret-token"
    assert "secret-token" not in result.stdout


def test_create_github_pull_request_redacts_token_from_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = create_repo(tmp_path)
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "secret-token")
    monkeypatch.setattr("app.tools.git_tools.shutil.which", lambda executable: "/usr/bin/gh")

    def fake_run(
        command: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(command, 0, stdout=f"{repo_path}\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="auth failed for secret-token",
        )

    monkeypatch.setattr("app.tools.git_tools.subprocess.run", fake_run)

    with pytest.raises(GitCommandError) as exc_info:
        create_github_pull_request(
            repo_path,
            base_branch="main",
            head_branch="feature/ping",
            title="Add ping",
            body="## Summary\n- Add ping\n",
            approved=True,
            token_env_vars=("TEST_GITHUB_TOKEN",),
        )

    assert "secret-token" not in exc_info.value.stderr
    assert "[REDACTED]" in exc_info.value.stderr
