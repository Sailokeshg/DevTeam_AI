"""Safe unified-diff parsing, application, and diff display tools."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.task import NonEmptyStr
from app.tools.file_tools import (
    FileToolError,
    PathTraversalError,
    read_file,
    resolve_repo_path,
    write_file,
)

HUNK_HEADER_PATTERN = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


class PatchToolError(ValueError):
    """Base exception for patch parsing and application failures."""


class PatchParseError(PatchToolError):
    """Raised when a unified diff cannot be parsed."""


class PatchApplyError(PatchToolError):
    """Raised when a parsed patch cannot be safely applied."""


@dataclass(frozen=True)
class UnifiedDiffHunk:
    """One hunk inside a unified diff file patch."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]


@dataclass(frozen=True)
class UnifiedDiffFile:
    """A file-level patch parsed from unified diff text."""

    old_path: str | None
    new_path: str | None
    hunks: list[UnifiedDiffHunk]

    @property
    def target_path(self) -> str:
        """Return the path that should appear in changed-file summaries."""
        path = self.new_path or self.old_path
        if path is None:
            raise PatchParseError("File patch is missing both old and new paths")
        return path

    @property
    def is_delete(self) -> bool:
        """Whether this patch deletes a file."""
        return self.new_path is None


class PatchApplyResult(BaseModel):
    """Result from applying a unified diff."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    changed_files: list[NonEmptyStr] = Field(min_length=1)
    applied_patch: NonEmptyStr


def parse_unified_diff(patch: str) -> list[UnifiedDiffFile]:
    """Parse unified diff text into file patches."""
    if not patch.strip():
        raise PatchParseError("Patch cannot be empty")

    lines = patch.splitlines(keepends=True)
    file_patches: list[UnifiedDiffFile] = []
    current_old_path: str | None = None
    current_new_path: str | None = None
    current_hunks: list[UnifiedDiffHunk] = []
    current_hunk: UnifiedDiffHunk | None = None

    def finish_hunk() -> None:
        nonlocal current_hunk
        if current_hunk is not None:
            current_hunks.append(current_hunk)
            current_hunk = None

    def finish_file() -> None:
        nonlocal current_old_path, current_new_path, current_hunks
        finish_hunk()
        if current_old_path is None and current_new_path is None:
            return
        if not current_hunks:
            path = current_new_path or current_old_path
            raise PatchParseError(f"File patch has no hunks: {path}")
        file_patches.append(
            UnifiedDiffFile(
                old_path=current_old_path,
                new_path=current_new_path,
                hunks=current_hunks,
            )
        )
        current_old_path = None
        current_new_path = None
        current_hunks = []

    for line in lines:
        line_without_newline = line.rstrip("\n")

        if line.startswith("diff --git "):
            finish_file()
            continue

        if current_hunk is None and line.startswith("--- "):
            current_old_path = _parse_diff_path(line_without_newline[4:])
            continue

        if current_hunk is None and line.startswith("+++ "):
            current_new_path = _parse_diff_path(line_without_newline[4:])
            continue

        if line.startswith("@@ "):
            finish_hunk()
            current_hunk = _parse_hunk_header(line_without_newline)
            continue

        if current_hunk is not None:
            if line.startswith("\\ No newline at end of file"):
                continue
            if not line or line[0] not in {" ", "+", "-"}:
                raise PatchParseError(f"Unsupported hunk line: {line_without_newline}")
            current_hunk.lines.append(line)

    finish_file()

    if not file_patches:
        raise PatchParseError("Patch did not contain any file changes")

    return file_patches


def validate_unified_diff(patch: str) -> None:
    """Validate that text is parseable unified diff."""
    parse_unified_diff(patch)


def apply_unified_diff(repo_path: str | Path, patch: str) -> PatchApplyResult:
    """Apply a unified diff safely inside a repository."""
    file_patches = parse_unified_diff(patch)
    changed_files: list[str] = []

    for file_patch in file_patches:
        if (
            file_patch.old_path is not None
            and file_patch.new_path is not None
            and file_patch.old_path != file_patch.new_path
        ):
            raise PatchApplyError("Renames are not supported by the Phase 5 patch applicator")

        target_path = file_patch.target_path
        if file_patch.is_delete:
            _apply_delete(repo_path, file_patch)
        else:
            source_lines = _read_source_lines(repo_path, file_patch.old_path)
            updated_content = _apply_hunks(source_lines, file_patch)
            write_file(repo_path, target_path, updated_content, create_parents=True)

        changed_files.append(target_path)

    return PatchApplyResult(changed_files=changed_files, applied_patch=patch)


def get_diff(repo_path: str | Path, relative_paths: list[str] | None = None) -> str:
    """Return the current git diff for a repository or selected paths."""
    repo_root = resolve_repo_path(repo_path)
    command = ["git", "-C", str(repo_root), "diff", "--"]

    if relative_paths is not None:
        for relative_path in relative_paths:
            validated_path = resolve_repo_path(repo_root, relative_path)
            command.append(validated_path.relative_to(repo_root).as_posix())

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PatchToolError(f"Unable to run git diff: {exc}") from exc

    if result.returncode != 0:
        raise PatchToolError(result.stderr.strip() or "git diff failed")

    return result.stdout


def _parse_hunk_header(line: str) -> UnifiedDiffHunk:
    match = HUNK_HEADER_PATTERN.match(line)
    if match is None:
        raise PatchParseError(f"Invalid hunk header: {line}")

    old_count = match.group("old_count")
    new_count = match.group("new_count")
    return UnifiedDiffHunk(
        old_start=int(match.group("old_start")),
        old_count=int(old_count) if old_count is not None else 1,
        new_start=int(match.group("new_start")),
        new_count=int(new_count) if new_count is not None else 1,
        lines=[],
    )


def _parse_diff_path(header_value: str) -> str | None:
    path_value = header_value.split("\t", maxsplit=1)[0].strip()
    if path_value == "/dev/null":
        return None
    if path_value.startswith("a/") or path_value.startswith("b/"):
        return path_value[2:]
    return path_value


def _read_source_lines(repo_path: str | Path, old_path: str | None) -> list[str]:
    if old_path is None:
        return []

    try:
        return read_file(repo_path, old_path).content.splitlines(keepends=True)
    except PathTraversalError:
        raise
    except FileToolError as exc:
        raise PatchApplyError(f"Cannot read file to patch: {old_path}") from exc


def _apply_delete(repo_path: str | Path, file_patch: UnifiedDiffFile) -> None:
    if file_patch.old_path is None:
        raise PatchApplyError("Delete patch is missing an old path")

    source_lines = _read_source_lines(repo_path, file_patch.old_path)
    _apply_hunks(source_lines, file_patch)
    target_path = resolve_repo_path(repo_path, file_patch.old_path)
    target_path.unlink()


def _apply_hunks(source_lines: list[str], file_patch: UnifiedDiffFile) -> str:
    output_lines: list[str] = []
    source_index = 0

    for hunk in file_patch.hunks:
        expected_index = max(hunk.old_start - 1, 0)
        if expected_index < source_index:
            raise PatchApplyError(f"Overlapping hunk for file: {file_patch.target_path}")

        output_lines.extend(source_lines[source_index:expected_index])
        source_index = expected_index

        for patch_line in hunk.lines:
            prefix = patch_line[0]
            content = patch_line[1:]

            if prefix == "+":
                output_lines.append(content)
                continue

            if source_index >= len(source_lines):
                raise PatchApplyError(f"Patch does not apply cleanly: {file_patch.target_path}")

            if source_lines[source_index] != content:
                raise PatchApplyError(f"Patch context mismatch: {file_patch.target_path}")

            if prefix == " ":
                output_lines.append(content)

            source_index += 1

    output_lines.extend(source_lines[source_index:])
    return "".join(output_lines)
