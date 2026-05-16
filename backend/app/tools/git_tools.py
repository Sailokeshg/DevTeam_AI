"""Safe Git and GitHub workflow helpers for DevTeam AI."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.tools.file_tools import FileToolError, resolve_repo_path

DEFAULT_REMOTE = "origin"
DEFAULT_TOKEN_ENV_VARS = ("GITHUB_TOKEN", "GH_TOKEN")
FORBIDDEN_REF_FRAGMENTS = ("..", "@{", "\\", " ", "~", "^", ":", "?", "*", "[", "\n")


class GitToolError(ValueError):
    """Raised when a Git tool cannot complete safely."""


class GitCommandError(GitToolError):
    """Raised when an underlying Git or GitHub CLI command fails."""

    def __init__(self, message: str, *, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


class GitApprovalError(GitToolError):
    """Raised when a network-mutating Git operation lacks approval."""


class GitHubConfigurationError(GitToolError):
    """Raised when optional GitHub PR creation is not configured."""


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    """Normalized result from a Git command."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class CloneResult:
    """Result from cloning a repository."""

    repository_url: str
    destination_path: Path
    command: list[str]


@dataclass(frozen=True, slots=True)
class BranchResult:
    """Result from creating or checking out a branch."""

    branch_name: str
    repository_path: Path
    checked_out: bool


@dataclass(frozen=True, slots=True)
class DiffResult:
    """Git diff output for a repository."""

    repository_path: Path
    diff: str
    changed_files: list[str]


@dataclass(frozen=True, slots=True)
class CommitResult:
    """Result from committing local changes."""

    commit_hash: str
    message: str
    changed_files: list[str]
    repository_path: Path


@dataclass(frozen=True, slots=True)
class PullRequestDraft:
    """Generated pull request title and body."""

    title: str
    body: str


@dataclass(frozen=True, slots=True)
class PushResult:
    """Result from pushing a branch to a remote."""

    remote: str
    branch_name: str
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class PullRequestResult:
    """Result from optional GitHub pull request creation."""

    url: str
    title: str
    body: str
    stdout: str


def clone_public_repo(
    repository_url: str | Path,
    destination_parent: str | Path,
    *,
    directory_name: str | None = None,
) -> CloneResult:
    """Clone a public repository URL or local test mirror into a destination directory."""
    source = _validate_clone_source(repository_url)
    parent = Path(destination_parent).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)

    destination = parent / (directory_name or _infer_repo_directory_name(source))
    if destination.exists():
        raise GitToolError(f"Clone destination already exists: {destination}")

    command = ["git", "clone", source, str(destination)]
    _run_command(command, cwd=parent)
    return CloneResult(repository_url=source, destination_path=destination, command=command)


def create_branch(
    repo_path: str | Path,
    branch_name: str,
    *,
    checkout: bool = True,
    start_point: str | None = None,
) -> BranchResult:
    """Create a branch in a local repository and optionally check it out."""
    repo_root = resolve_git_repo(repo_path)
    _validate_branch_name(branch_name)
    if start_point is not None:
        _validate_refish(start_point)

    command = ["git", "checkout", "-b", branch_name]
    if not checkout:
        command = ["git", "branch", branch_name]
    if start_point is not None:
        command.append(start_point)

    _run_command(command, cwd=repo_root)
    return BranchResult(branch_name=branch_name, repository_path=repo_root, checked_out=checkout)


def get_git_diff(
    repo_path: str | Path,
    *,
    staged: bool = False,
    base_ref: str | None = None,
) -> DiffResult:
    """Return the current Git diff and changed files for a local repository."""
    repo_root = resolve_git_repo(repo_path)
    if base_ref is not None:
        _validate_refish(base_ref)

    diff_command = ["git", "diff"]
    files_command = ["git", "diff", "--name-only"]
    if staged:
        diff_command.append("--cached")
        files_command.append("--cached")
    if base_ref is not None:
        diff_command.extend([base_ref, "--"])
        files_command.extend([base_ref, "--"])

    diff = _run_command(diff_command, cwd=repo_root).stdout
    changed_files_output = _run_command(files_command, cwd=repo_root).stdout
    changed_files = [line for line in changed_files_output.splitlines() if line]
    return DiffResult(repository_path=repo_root, diff=diff, changed_files=changed_files)


def commit_changes(
    repo_path: str | Path,
    message: str,
    *,
    paths: Sequence[str] | None = None,
    allow_empty: bool = False,
    author_name: str | None = None,
    author_email: str | None = None,
) -> CommitResult:
    """Stage selected changes and create a local commit."""
    repo_root = resolve_git_repo(repo_path)
    commit_message = _validate_commit_message(message)

    if paths is None:
        _run_command(["git", "add", "--all"], cwd=repo_root)
    else:
        safe_paths = [_validate_repo_relative_path(path) for path in paths]
        if safe_paths:
            _run_command(["git", "add", "--", *safe_paths], cwd=repo_root)

    changed_files_output = _run_command(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_root,
    ).stdout
    changed_files = [line for line in changed_files_output.splitlines() if line]
    if not changed_files and not allow_empty:
        raise GitToolError("No staged changes to commit")

    command = ["git"]
    if author_name:
        command.extend(["-c", f"user.name={author_name}"])
    if author_email:
        command.extend(["-c", f"user.email={author_email}"])
    command.extend(["commit", "-m", commit_message])
    if allow_empty:
        command.append("--allow-empty")

    _run_command(command, cwd=repo_root)
    commit_hash = _run_command(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    return CommitResult(
        commit_hash=commit_hash,
        message=commit_message,
        changed_files=changed_files,
        repository_path=repo_root,
    )


def generate_pr_title_body(
    feature_request: str,
    *,
    changed_files: Sequence[str] | None = None,
    test_summary: str | None = None,
    quality_summary: str | None = None,
    implementation_summary: str | None = None,
) -> PullRequestDraft:
    """Generate a deterministic PR title/body from run outputs without an LLM."""
    request = _normalize_non_empty(feature_request, "feature_request")
    title = _truncate_title(f"Implement {request.rstrip('.')}")
    files = list(changed_files or [])
    summary = implementation_summary or request

    changed_file_lines = "\n".join(f"- `{path}`" for path in files) if files else "- None recorded"
    body = (
        "## Summary\n"
        f"- {summary}\n\n"
        "## Changed Files\n"
        f"{changed_file_lines}\n\n"
        "## Tests\n"
        f"- {test_summary or 'Not run'}\n\n"
        "## Quality Gates\n"
        f"- {quality_summary or 'Not run'}\n\n"
        "## Safety\n"
        "- Generated by DevTeam AI; review before merging.\n"
    )
    return PullRequestDraft(title=title, body=body)


def push_branch(
    repo_path: str | Path,
    *,
    branch_name: str | None = None,
    remote: str = DEFAULT_REMOTE,
    approved: bool = False,
) -> PushResult:
    """Push a branch only after explicit caller approval."""
    if not approved:
        raise GitApprovalError("Pushing branches requires explicit user approval")

    repo_root = resolve_git_repo(repo_path)
    remote_name = _validate_remote_name(remote)
    active_branch = branch_name or get_current_branch(repo_root)
    _validate_branch_name(active_branch)

    result = _run_command(["git", "push", "-u", remote_name, active_branch], cwd=repo_root)
    return PushResult(
        remote=remote_name,
        branch_name=active_branch,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def create_github_pull_request(
    repo_path: str | Path,
    *,
    base_branch: str,
    head_branch: str,
    title: str,
    body: str,
    approved: bool = False,
    token_env_vars: Sequence[str] = DEFAULT_TOKEN_ENV_VARS,
) -> PullRequestResult:
    """Create a GitHub PR via the `gh` CLI when token auth and approval are present."""
    if not approved:
        raise GitApprovalError("Creating pull requests requires explicit user approval")

    repo_root = resolve_git_repo(repo_path)
    _validate_branch_name(base_branch)
    _validate_branch_name(head_branch)
    pr_title = _normalize_non_empty(title, "title")
    pr_body = _normalize_non_empty(body, "body")
    gh_path = shutil.which("gh")
    if gh_path is None:
        raise GitHubConfigurationError("GitHub CLI `gh` is not installed")

    token = _read_github_token(token_env_vars)
    env = dict(os.environ)
    env["GH_TOKEN"] = token
    env.setdefault("GITHUB_TOKEN", token)

    command = [
        gh_path,
        "pr",
        "create",
        "--base",
        base_branch,
        "--head",
        head_branch,
        "--title",
        pr_title,
        "--body",
        pr_body,
    ]
    result = _run_command(command, cwd=repo_root, env=env, secret_values=[token])
    url = _extract_pr_url(result.stdout)
    return PullRequestResult(url=url, title=pr_title, body=pr_body, stdout=result.stdout)


def get_current_branch(repo_path: str | Path) -> str:
    """Return the current branch name for a local repository."""
    repo_root = resolve_git_repo(repo_path)
    branch = _run_command(["git", "branch", "--show-current"], cwd=repo_root).stdout.strip()
    if not branch:
        raise GitToolError("Repository is in detached HEAD state")
    return branch


def resolve_git_repo(repo_path: str | Path) -> Path:
    """Resolve and validate a local Git repository path."""
    try:
        repo_root = resolve_repo_path(repo_path)
    except FileToolError as exc:
        raise GitToolError(f"Invalid repository path: {exc}") from exc

    result = _run_command(["git", "rev-parse", "--show-toplevel"], cwd=repo_root)
    return Path(result.stdout.strip()).resolve()


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    secret_values: Sequence[str] = (),
) -> GitCommandResult:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise GitCommandError(f"Unable to run command `{command[0]}`: {exc}") from exc

    stdout = _sanitize(result.stdout or "", secret_values)
    stderr = _sanitize(result.stderr or "", secret_values)
    if result.returncode != 0:
        raise GitCommandError(
            f"Command failed with exit code {result.returncode}: {_redacted_command(command)}",
            stdout=stdout,
            stderr=stderr,
        )

    return GitCommandResult(
        command=list(command),
        return_code=result.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _validate_clone_source(repository_url: str | Path) -> str:
    source = str(repository_url).strip()
    if not source:
        raise GitToolError("Repository URL cannot be empty")
    if any(fragment in source for fragment in ("\n", "\r", "\t")):
        raise GitToolError("Repository URL cannot contain control characters")

    local_path = Path(source).expanduser()
    if local_path.exists():
        return str(local_path.resolve())

    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        if parsed.username or parsed.password:
            raise GitToolError("Repository URL cannot include embedded credentials")
        if not parsed.netloc:
            raise GitToolError("Repository URL must include a host")
        return source

    if _is_ssh_git_url(source):
        return source

    raise GitToolError("Repository source must be an HTTP(S), SSH Git URL, or local path")


def _infer_repo_directory_name(source: str) -> str:
    if _is_ssh_git_url(source):
        raw_name = source.rsplit(":", maxsplit=1)[-1].rsplit("/", maxsplit=1)[-1]
    else:
        raw_name = Path(urlparse(source).path).name or Path(source).name
    name = raw_name.removesuffix(".git")
    if not name:
        raise GitToolError("Could not infer clone directory name")
    return _validate_directory_name(name)


def _is_ssh_git_url(source: str) -> bool:
    return bool(re.match(r"^[\w.-]+@[\w.-]+:[\w./-]+(?:\.git)?$", source))


def _validate_directory_name(name: str) -> str:
    if not name or name in {".", ".."}:
        raise GitToolError("Directory name cannot be empty or relative")
    if any(fragment in name for fragment in ("/", "\\", "\n", "\r", "\t")):
        raise GitToolError("Directory name must be a single safe path segment")
    return name


def _validate_branch_name(branch_name: str) -> str:
    branch = _normalize_non_empty(branch_name, "branch_name")
    if branch.startswith("-") or branch.startswith("/") or branch.endswith("/"):
        raise GitToolError("Invalid branch name")
    if branch.endswith(".") or ".lock" in branch:
        raise GitToolError("Invalid branch name")
    if any(fragment in branch for fragment in FORBIDDEN_REF_FRAGMENTS):
        raise GitToolError("Invalid branch name")
    return branch


def _validate_refish(refish: str) -> str:
    ref = _normalize_non_empty(refish, "refish")
    if ref.startswith("-"):
        raise GitToolError("Invalid Git reference")
    if any(fragment in ref for fragment in FORBIDDEN_REF_FRAGMENTS):
        raise GitToolError("Invalid Git reference")
    return ref


def _validate_remote_name(remote: str) -> str:
    name = _normalize_non_empty(remote, "remote")
    if name.startswith("-") or any(fragment in name for fragment in ("/", "\\", "\n", " ")):
        raise GitToolError("Invalid remote name")
    return name


def _validate_commit_message(message: str) -> str:
    commit_message = _normalize_non_empty(message, "message")
    if "\x00" in commit_message:
        raise GitToolError("Commit message cannot contain null bytes")
    return commit_message


def _validate_repo_relative_path(path: str) -> str:
    value = _normalize_non_empty(path, "path")
    candidate = Path(value)
    if candidate.is_absolute() or value == ".." or value.startswith("../") or "/../" in value:
        raise GitToolError("Git paths must stay inside the repository")
    return value


def _read_github_token(token_env_vars: Sequence[str]) -> str:
    for env_var in token_env_vars:
        token = os.getenv(env_var)
        if token:
            return token
    names = ", ".join(token_env_vars)
    raise GitHubConfigurationError(f"GitHub token is not configured; set one of: {names}")


def _extract_pr_url(stdout: str) -> str:
    for token in stdout.split():
        if token.startswith("https://") and "/pull/" in token:
            return token.strip()
    return stdout.strip()


def _truncate_title(title: str, max_length: int = 72) -> str:
    normalized = " ".join(title.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def _normalize_non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise GitToolError(f"{field_name} cannot be empty")
    return normalized


def _sanitize(output: str, secret_values: Sequence[str]) -> str:
    sanitized = output
    for secret in secret_values:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized


def _redacted_command(command: Sequence[str]) -> str:
    return " ".join("[REDACTED]" if "TOKEN" in part.upper() else part for part in command)
