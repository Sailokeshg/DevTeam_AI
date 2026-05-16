"""Run deterministic Phase 15 evaluations for the FastAPI demo app."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

TOOL_BIN_DIR = Path(sys.executable).parent
os.environ["PATH"] = f"{TOOL_BIN_DIR}{os.pathsep}{os.environ.get('PATH', '')}"

from app.tools.static_analysis import QualityGateResult, run_all_quality_gates  # noqa: E402
from app.tools.test_runner import run_pytest  # noqa: E402

TASKS_PATH = REPO_ROOT / "examples" / "fastapi-demo-app" / "evaluation_tasks.json"
DEMO_REPO_PATH = REPO_ROOT / "examples" / "fastapi-demo-app"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "example-runs"


@dataclass(frozen=True, slots=True)
class EvaluationTask:
    """Curated demo task metadata used by the evaluation harness."""

    id: str
    title: str
    feature_request: str
    pytest_targets: list[str]
    expected_files_changed: list[str]
    recorded_iterations: int
    expected_quality_gate_status: str


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Structured output for a single curated task evaluation."""

    task_id: str
    title: str
    feature_request: str
    status: str
    iterations: int
    files_changed: list[str]
    tests_passed: int
    tests_failed: int
    quality_gate_status: str
    quality_gates: dict[str, str]
    pytest_targets: list[str]
    notes: str

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "feature_request": self.feature_request,
            "status": self.status,
            "iterations": self.iterations,
            "files_changed": self.files_changed,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "quality_gate_status": self.quality_gate_status,
            "quality_gates": self.quality_gates,
            "pytest_targets": self.pytest_targets,
            "notes": self.notes,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate curated DevTeam AI demo tasks.")
    parser.add_argument(
        "--task",
        action="append",
        dest="task_ids",
        help="Task id to evaluate. Repeat to run multiple tasks. Defaults to all tasks.",
    )
    parser.add_argument(
        "--tasks-file",
        type=Path,
        default=TASKS_PATH,
        help="Path to the curated task JSON file.",
    )
    parser.add_argument(
        "--demo-repo",
        type=Path,
        default=DEMO_REPO_PATH,
        help="Path to the FastAPI demo app repository.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where JSON and Markdown evaluation outputs are written.",
    )
    args = parser.parse_args()

    tasks = load_tasks(args.tasks_file)
    selected_tasks = filter_tasks(tasks, args.task_ids)
    results = [evaluate_task(task, args.demo_repo) for task in selected_tasks]
    write_outputs(results, args.output_dir)
    print(render_markdown_table(results))


def load_tasks(tasks_path: Path) -> list[EvaluationTask]:
    raw_tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    return [
        EvaluationTask(
            id=str(task["id"]),
            title=str(task["title"]),
            feature_request=str(task["feature_request"]),
            pytest_targets=[str(target) for target in task["pytest_targets"]],
            expected_files_changed=[str(path) for path in task["expected_files_changed"]],
            recorded_iterations=int(task["recorded_iterations"]),
            expected_quality_gate_status=str(task["expected_quality_gate_status"]),
        )
        for task in raw_tasks
    ]


def filter_tasks(tasks: list[EvaluationTask], task_ids: list[str] | None) -> list[EvaluationTask]:
    if not task_ids:
        return tasks

    requested = set(task_ids)
    selected = [task for task in tasks if task.id in requested]
    missing = sorted(requested - {task.id for task in selected})
    if missing:
        raise SystemExit(f"Unknown task id(s): {', '.join(missing)}")
    return selected


def evaluate_task(task: EvaluationTask, demo_repo_path: Path) -> EvaluationResult:
    """Run pytest targets and quality gates for one curated task."""
    targeted_tests = run_pytest(
        demo_repo_path,
        args=["-q", *task.pytest_targets],
        timeout_seconds=60,
    )
    quality_result = run_all_quality_gates(
        demo_repo_path,
        include_semgrep=False,
        pytest_timeout_seconds=60,
        static_timeout_seconds=60,
    )
    quality_gate_status = "passed" if quality_result.all_passed else "failed"
    status = "passed" if targeted_tests.success and quality_result.all_passed else "failed"

    return EvaluationResult(
        task_id=task.id,
        title=task.title,
        feature_request=task.feature_request,
        status=status,
        iterations=task.recorded_iterations,
        files_changed=task.expected_files_changed,
        tests_passed=targeted_tests.passed_count,
        tests_failed=targeted_tests.failed_count,
        quality_gate_status=quality_gate_status,
        quality_gates=summarize_quality_gates(quality_result),
        pytest_targets=task.pytest_targets,
        notes=(
            "Deterministic Phase 15 demo evaluation. Iterations and files_changed are "
            "recorded curated-run metadata; tests and quality gates are executed live."
        ),
    )


def summarize_quality_gates(quality_result: QualityGateResult) -> dict[str, str]:
    summary = {"pytest": "passed" if quality_result.test_result.success else "failed"}
    for result in quality_result.static_analysis_results:
        if result.skipped:
            summary[result.tool] = "skipped"
        else:
            summary[result.tool] = "passed" if result.success else "failed"
    return summary


def write_outputs(results: list[EvaluationResult], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        output_path = output_dir / f"{result.task_id}.json"
        output_path.write_text(
            json.dumps(result.to_json_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    (output_dir / "summary.md").write_text(render_summary_markdown(results), encoding="utf-8")


def render_summary_markdown(results: list[EvaluationResult]) -> str:
    return (
        "# DevTeam AI Example Runs\n\n"
        "These outputs are generated by `scripts/evaluate_demo_tasks.py`. The harness runs "
        "curated pytest targets and the quality gates against `examples/fastapi-demo-app`, "
        "then writes one JSON artifact per task.\n\n"
        f"{render_markdown_table(results)}\n"
    )


def render_markdown_table(results: list[EvaluationResult]) -> str:
    lines = [
        "| Task | Status | Iterations | Files Changed | Tests Passed | Quality Gate |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        lines.append(
            "| "
            f"{result.title} | {result.status} | {result.iterations} | "
            f"{len(result.files_changed)} | {result.tests_passed} | "
            f"{result.quality_gate_status} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
