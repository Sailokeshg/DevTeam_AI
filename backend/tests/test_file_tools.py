"""Tests for safe repository inspection file tools."""

from pathlib import Path

import pytest

from app.tools.file_tools import (
    FileToolError,
    PathTraversalError,
    list_files,
    read_file,
    search_code,
    summarize_repository_tree,
    write_file,
)


def create_demo_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()
    (repo_path / "app").mkdir()
    (repo_path / "tests").mkdir()
    (repo_path / ".git").mkdir()
    (repo_path / "__pycache__").mkdir()
    (repo_path / "node_modules").mkdir()

    (repo_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (repo_path / "app" / "main.py").write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
        encoding="utf-8",
    )
    (repo_path / "tests" / "test_main.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )
    (repo_path / ".git" / "config").write_text("[remote]\n", encoding="utf-8")
    (repo_path / "__pycache__" / "main.pyc").write_text("ignored", encoding="utf-8")
    (repo_path / "node_modules" / "package.json").write_text("{}", encoding="utf-8")

    return repo_path


def test_list_files_ignores_common_generated_directories(tmp_path: Path) -> None:
    repo_path = create_demo_repo(tmp_path)

    entries = list_files(repo_path, include_directories=True)
    paths = {entry.path for entry in entries}

    assert "README.md" in paths
    assert "app" in paths
    assert "app/main.py" in paths
    assert "tests/test_main.py" in paths
    assert ".git/config" not in paths
    assert "__pycache__/main.pyc" not in paths
    assert "node_modules/package.json" not in paths


def test_read_file_rejects_path_traversal_and_ignored_paths(tmp_path: Path) -> None:
    repo_path = create_demo_repo(tmp_path)
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret", encoding="utf-8")

    result = read_file(repo_path, "app/main.py")

    assert "FastAPI" in result.content
    assert result.path == "app/main.py"

    with pytest.raises(PathTraversalError):
        read_file(repo_path, "../outside.txt")

    with pytest.raises(FileToolError, match="ignored directory"):
        read_file(repo_path, ".git/config")


def test_write_file_validates_paths_and_can_create_parent_dirs(tmp_path: Path) -> None:
    repo_path = create_demo_repo(tmp_path)

    result = write_file(repo_path, "app/generated.py", "VALUE = 1\n")

    assert result.path == "app/generated.py"
    assert result.bytes_written == len(b"VALUE = 1\n")
    assert (repo_path / "app" / "generated.py").read_text(encoding="utf-8") == "VALUE = 1\n"

    nested_result = write_file(
        repo_path,
        "new_package/module.py",
        "NAME = 'demo'\n",
        create_parents=True,
    )

    assert nested_result.path == "new_package/module.py"
    assert (repo_path / "new_package" / "module.py").exists()

    with pytest.raises(PathTraversalError):
        write_file(repo_path, "../outside.txt", "nope\n")

    with pytest.raises(FileToolError, match="ignored directory"):
        write_file(repo_path, ".git/hooks/pre-commit", "nope\n", create_parents=True)


def test_search_code_returns_line_level_matches(tmp_path: Path) -> None:
    repo_path = create_demo_repo(tmp_path)

    matches = search_code(repo_path, "fastapi", case_sensitive=False)

    assert len(matches) == 2
    assert matches[0].path == "app/main.py"
    assert matches[0].line_number == 1
    assert matches[0].line == "from fastapi import FastAPI"


def test_summarize_repository_tree_counts_small_python_repo(tmp_path: Path) -> None:
    repo_path = create_demo_repo(tmp_path)

    summary = summarize_repository_tree(repo_path)

    assert summary.total_files == 3
    assert summary.total_directories == 2
    assert summary.file_extensions == {".md": 1, ".py": 2}
    assert "demo-repo/" in summary.tree
    assert "app/" in summary.tree
    assert "main.py" in summary.tree
    assert ".git" not in summary.tree
    assert "node_modules" not in summary.tree


def test_symlinks_pointing_outside_repo_are_not_read(tmp_path: Path) -> None:
    repo_path = create_demo_repo(tmp_path)
    outside_file = tmp_path / "outside.py"
    outside_file.write_text("SECRET = True\n", encoding="utf-8")
    symlink_path = repo_path / "app" / "outside_link.py"

    try:
        symlink_path.symlink_to(outside_file)
    except OSError:
        pytest.skip("Symlinks are not available in this environment")

    listed_paths = {entry.path for entry in list_files(repo_path)}

    assert "app/outside_link.py" not in listed_paths
    with pytest.raises(PathTraversalError):
        read_file(repo_path, "app/outside_link.py")
