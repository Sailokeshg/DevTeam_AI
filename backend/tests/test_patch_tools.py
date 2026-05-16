"""Tests for Phase 5 unified-diff patch tools."""

import subprocess
from pathlib import Path

import pytest

from app.tools.file_tools import PathTraversalError, read_file
from app.tools.patch_tools import (
    PatchApplyError,
    PatchParseError,
    apply_unified_diff,
    get_diff,
    parse_unified_diff,
)


def init_git_repo(repo_path: Path) -> None:
    """Initialize a tiny git repo for diff display tests."""
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=DevTeam AI Tests",
            "-c",
            "user.email=devteam-ai@example.test",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )


def create_demo_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()
    (repo_path / "app.py").write_text(
        'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
        encoding="utf-8",
    )
    init_git_repo(repo_path)
    return repo_path


def test_parse_unified_diff_returns_file_patch() -> None:
    patch = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet(name: str) -> str:\n"
        '-    return f"Hello, {name}!"\n'
        '+    return f"Hi, {name}!"\n'
    )

    file_patches = parse_unified_diff(patch)

    assert len(file_patches) == 1
    assert file_patches[0].old_path == "app.py"
    assert file_patches[0].new_path == "app.py"
    assert len(file_patches[0].hunks) == 1


def test_apply_unified_diff_updates_demo_repo_and_get_diff_displays_result(tmp_path: Path) -> None:
    repo_path = create_demo_repo(tmp_path)
    patch = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet(name: str) -> str:\n"
        '-    return f"Hello, {name}!"\n'
        '+    return f"Hi, {name}!"\n'
    )

    result = apply_unified_diff(repo_path, patch)
    diff = get_diff(repo_path)

    assert result.changed_files == ["app.py"]
    assert read_file(repo_path, "app.py").content == (
        'def greet(name: str) -> str:\n    return f"Hi, {name}!"\n'
    )
    assert "diff --git a/app.py b/app.py" in diff
    assert '+    return f"Hi, {name}!"' in diff


def test_apply_unified_diff_can_create_new_file(tmp_path: Path) -> None:
    repo_path = create_demo_repo(tmp_path)
    patch = (
        "diff --git a/utils.py b/utils.py\n"
        "--- /dev/null\n"
        "+++ b/utils.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def add(left: int, right: int) -> int:\n"
        "+    return left + right\n"
    )

    result = apply_unified_diff(repo_path, patch)

    assert result.changed_files == ["utils.py"]
    assert read_file(repo_path, "utils.py").content == (
        "def add(left: int, right: int) -> int:\n    return left + right\n"
    )


def test_apply_unified_diff_rejects_context_mismatch(tmp_path: Path) -> None:
    repo_path = create_demo_repo(tmp_path)
    patch = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def missing(name: str) -> str:\n"
        '-    return "missing"\n'
        '+    return "still missing"\n'
    )

    with pytest.raises(PatchApplyError, match="context mismatch"):
        apply_unified_diff(repo_path, patch)


def test_apply_unified_diff_rejects_path_traversal(tmp_path: Path) -> None:
    repo_path = create_demo_repo(tmp_path)
    patch = (
        "diff --git a/../outside.py b/../outside.py\n"
        "--- a/../outside.py\n"
        "+++ b/../outside.py\n"
        "@@ -0,0 +1 @@\n"
        "+SECRET = True\n"
    )

    with pytest.raises(PathTraversalError):
        apply_unified_diff(repo_path, patch)


def test_parse_unified_diff_rejects_non_patch_text() -> None:
    with pytest.raises(PatchParseError):
        parse_unified_diff("not a patch")
