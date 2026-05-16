"""Safe repository file inspection tools."""

import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.task import NonEmptyStr

IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "node_modules",
        "dist",
        "build",
        ".pytest_cache",
    }
)


class FileToolError(ValueError):
    """Base exception for file tool validation and access errors."""


class PathTraversalError(FileToolError):
    """Raised when a requested path escapes the selected repository root."""


class FileEntry(BaseModel):
    """A file or directory entry inside a repository."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    path: NonEmptyStr
    is_dir: bool
    size_bytes: int | None = Field(default=None, ge=0)


class FileReadResult(BaseModel):
    """Result from reading a repository file."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    path: NonEmptyStr
    content: str


class FileWriteResult(BaseModel):
    """Result from writing a repository file."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    path: NonEmptyStr
    bytes_written: int = Field(ge=0)


class SearchMatch(BaseModel):
    """A single code search result."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    path: NonEmptyStr
    line_number: int = Field(ge=1)
    line: str


class RepositorySummary(BaseModel):
    """A compact repository tree summary."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    root_path: NonEmptyStr
    tree: str
    total_files: int = Field(ge=0)
    total_directories: int = Field(ge=0)
    file_extensions: dict[str, int]
    truncated: bool = False


def resolve_repo_path(repo_path: str | Path, relative_path: str | Path = ".") -> Path:
    """Resolve and validate a path inside a selected repository."""
    repo_root = _resolve_repo_root(repo_path)
    requested_path = Path(relative_path).expanduser()

    candidate = requested_path if requested_path.is_absolute() else repo_root / requested_path
    resolved_path = candidate.resolve(strict=False)

    if not _is_within_repo(repo_root, resolved_path):
        raise PathTraversalError(f"Path escapes repository root: {relative_path}")

    if _is_ignored_relative_path(resolved_path.relative_to(repo_root)):
        raise FileToolError(f"Path is inside an ignored directory: {relative_path}")

    return resolved_path


def list_files(repo_path: str | Path, *, include_directories: bool = False) -> list[FileEntry]:
    """List repository files while ignoring generated and dependency directories."""
    repo_root = _resolve_repo_root(repo_path)
    entries: list[FileEntry] = []

    for path in _iter_repository_paths(repo_root, include_directories=include_directories):
        relative_path = _relative_posix(repo_root, path)
        entries.append(
            FileEntry(
                path=relative_path,
                is_dir=path.is_dir(),
                size_bytes=path.stat().st_size if path.is_file() else None,
            )
        )

    return entries


def read_file(repo_path: str | Path, relative_path: str | Path) -> FileReadResult:
    """Read a text file inside the repository after path validation."""
    file_path = resolve_repo_path(repo_path, relative_path)

    if not file_path.is_file():
        raise FileToolError(f"Path is not a file: {relative_path}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise FileToolError(f"File is not valid UTF-8 text: {relative_path}") from exc

    return FileReadResult(
        path=_relative_posix(_resolve_repo_root(repo_path), file_path),
        content=content,
    )


def write_file(
    repo_path: str | Path,
    relative_path: str | Path,
    content: str,
    *,
    create_parents: bool = False,
) -> FileWriteResult:
    """Write a text file inside the repository after path validation."""
    file_path = resolve_repo_path(repo_path, relative_path)
    repo_root = _resolve_repo_root(repo_path)

    if file_path.exists() and file_path.is_dir():
        raise FileToolError(f"Path is a directory, not a file: {relative_path}")

    if create_parents:
        parent_path = resolve_repo_path(repo_path, file_path.parent)
        parent_path.mkdir(parents=True, exist_ok=True)
    elif not file_path.parent.exists():
        raise FileToolError(f"Parent directory does not exist: {file_path.parent}")

    file_path.write_text(content, encoding="utf-8")
    return FileWriteResult(
        path=_relative_posix(repo_root, file_path),
        bytes_written=len(content.encode("utf-8")),
    )


def search_code(
    repo_path: str | Path,
    query: str,
    *,
    case_sensitive: bool = True,
    regex: bool = False,
    max_results: int = 100,
) -> list[SearchMatch]:
    """Search text files in a repository and return line-level matches."""
    if not query:
        raise FileToolError("Search query cannot be empty")
    if max_results < 1:
        raise FileToolError("max_results must be at least 1")

    repo_root = _resolve_repo_root(repo_path)
    matches: list[SearchMatch] = []
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(query, flags=flags) if regex else None
    normalized_query = query if case_sensitive else query.lower()

    for entry in list_files(repo_root):
        file_path = resolve_repo_path(repo_root, entry.path)

        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue

        for line_number, line in enumerate(lines, start=1):
            haystack = line if case_sensitive else line.lower()
            is_match = (
                bool(pattern.search(line)) if pattern is not None else normalized_query in haystack
            )
            if not is_match:
                continue

            matches.append(SearchMatch(path=entry.path, line_number=line_number, line=line))
            if len(matches) >= max_results:
                return matches

    return matches


def summarize_repository_tree(
    repo_path: str | Path,
    *,
    max_depth: int = 3,
    max_entries: int = 200,
) -> RepositorySummary:
    """Summarize a repository as a compact tree with basic file statistics."""
    if max_depth < 0:
        raise FileToolError("max_depth cannot be negative")
    if max_entries < 1:
        raise FileToolError("max_entries must be at least 1")

    repo_root = _resolve_repo_root(repo_path)
    lines = [f"{repo_root.name}/"]
    state = _TreeState(max_entries=max_entries)

    _append_tree_lines(
        current_path=repo_root,
        lines=lines,
        state=state,
        prefix="",
        depth=0,
        max_depth=max_depth,
    )

    total_files = 0
    total_directories = 0
    extensions: Counter[str] = Counter()

    for path in _iter_repository_paths(repo_root, include_directories=True):
        if path.is_dir():
            total_directories += 1
            continue

        total_files += 1
        suffix = path.suffix or "[no extension]"
        extensions[suffix] += 1

    return RepositorySummary(
        root_path=str(repo_root),
        tree="\n".join(lines),
        total_files=total_files,
        total_directories=total_directories,
        file_extensions=dict(sorted(extensions.items())),
        truncated=state.truncated,
    )


class _TreeState:
    """Mutable tree-rendering limits."""

    def __init__(self, max_entries: int):
        self.max_entries = max_entries
        self.rendered_entries = 0
        self.truncated = False


def _resolve_repo_root(repo_path: str | Path) -> Path:
    repo_root = Path(repo_path).expanduser().resolve(strict=True)

    if not repo_root.is_dir():
        raise FileToolError(f"Repository path is not a directory: {repo_path}")

    return repo_root


def _iter_repository_paths(repo_root: Path, *, include_directories: bool = False) -> list[Path]:
    paths: list[Path] = []
    stack = [repo_root]

    while stack:
        current_path = stack.pop()
        children = _visible_children(current_path)

        for child in reversed(children):
            if child.is_dir():
                stack.append(child)

        for child in children:
            if include_directories or child.is_file():
                paths.append(child)

    return paths


def _append_tree_lines(
    *,
    current_path: Path,
    lines: list[str],
    state: _TreeState,
    prefix: str,
    depth: int,
    max_depth: int,
) -> None:
    if depth >= max_depth or state.truncated:
        return

    children = _visible_children(current_path)

    for index, child in enumerate(children):
        if state.rendered_entries >= state.max_entries:
            state.truncated = True
            lines.append(f"{prefix}...")
            return

        connector = "`-- " if index == len(children) - 1 else "|-- "
        display_name = f"{child.name}/" if child.is_dir() else child.name
        lines.append(f"{prefix}{connector}{display_name}")
        state.rendered_entries += 1

        if child.is_dir():
            extension = "    " if index == len(children) - 1 else "|   "
            _append_tree_lines(
                current_path=child,
                lines=lines,
                state=state,
                prefix=f"{prefix}{extension}",
                depth=depth + 1,
                max_depth=max_depth,
            )


def _visible_children(path: Path) -> list[Path]:
    children = [
        child
        for child in path.iterdir()
        if child.name not in IGNORED_DIRECTORIES and not child.is_symlink()
    ]
    return sorted(children, key=lambda child: (not child.is_dir(), child.name.lower()))


def _is_within_repo(repo_root: Path, path: Path) -> bool:
    return path == repo_root or repo_root in path.parents


def _is_ignored_relative_path(relative_path: Path) -> bool:
    return any(part in IGNORED_DIRECTORIES for part in relative_path.parts)


def _relative_posix(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()
