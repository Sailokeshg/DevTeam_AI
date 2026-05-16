"""Core API routes."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.graph import run_devteam_workflow
from app.schemas.agent_state import AgentState
from app.schemas.task import NonEmptyStr
from app.storage.sqlite_store import RunNotFoundError, SQLiteRunStore, StoredRun

router = APIRouter()

WorkflowRunner = Callable[..., AgentState]
_DEFAULT_RUN_STORE: SQLiteRunStore | None = None


class RunCreateRequest(BaseModel):
    """Request body for starting a synchronous local workflow run."""

    repository_path: NonEmptyStr = Field(description="Local repository path to analyze and modify.")
    feature_request: NonEmptyStr = Field(description="Feature request or bug fix for DevTeam AI.")
    max_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum repair iterations before the workflow stops.",
    )


class RunResponse(BaseModel):
    """Saved workflow run state returned by the API."""

    run_id: str
    status: str
    repository_path: str
    feature_request: str
    created_at: str
    updated_at: str
    state: AgentState


class RunDiffResponse(BaseModel):
    """Final diff for a saved run."""

    run_id: str
    diff: str


class RunLogEntry(BaseModel):
    """Human-readable run log item derived from AgentState outputs."""

    source: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class RunLogsResponse(BaseModel):
    """Agent outputs and quality gate logs for a saved run."""

    run_id: str
    logs: list[RunLogEntry]


def get_run_store() -> SQLiteRunStore:
    """Return the process-wide run store, created lazily for testability."""
    global _DEFAULT_RUN_STORE
    if _DEFAULT_RUN_STORE is None:
        _DEFAULT_RUN_STORE = SQLiteRunStore.from_env()
    return _DEFAULT_RUN_STORE


def get_workflow_runner() -> WorkflowRunner:
    """Return the production workflow runner dependency."""
    return run_devteam_workflow


@router.get("/health")
def health_check() -> dict[str, str]:
    """Simple service health endpoint."""
    return {"status": "ok"}


@router.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["runs"],
)
def create_run(
    request: RunCreateRequest,
    store: Annotated[SQLiteRunStore, Depends(get_run_store)],
    workflow_runner: Annotated[WorkflowRunner, Depends(get_workflow_runner)],
) -> RunResponse:
    """Start a synchronous DevTeam AI workflow run for a local repository."""
    record = store.create_run(
        repository_path=request.repository_path,
        feature_request=request.feature_request,
    )

    try:
        final_state = workflow_runner(
            repo_path=request.repository_path,
            feature_request=request.feature_request,
            max_iterations=request.max_iterations,
        )
    except Exception as exc:
        failed_state = AgentState(
            user_request=request.feature_request,
            repository_path=request.repository_path,
            repository_summary=f"Workflow failed: {exc}",
            final_status="failed",
        )
        store.update_run_state(record.run_id, failed_state)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow run failed: {exc}",
        ) from exc

    return _record_to_response(store.update_run_state(record.run_id, final_state))


@router.get("/runs/{run_id}", response_model=RunResponse, tags=["runs"])
def get_run(
    run_id: str,
    store: Annotated[SQLiteRunStore, Depends(get_run_store)],
) -> RunResponse:
    """Return the saved state for a workflow run."""
    return _record_to_response(_get_record_or_404(store, run_id))


@router.get("/runs/{run_id}/diff", response_model=RunDiffResponse, tags=["runs"])
def get_run_diff(
    run_id: str,
    store: Annotated[SQLiteRunStore, Depends(get_run_store)],
) -> RunDiffResponse:
    """Return the final diff captured for a workflow run."""
    record = _get_record_or_404(store, run_id)
    return RunDiffResponse(run_id=record.run_id, diff=record.state.diff or "")


@router.get("/runs/{run_id}/logs", response_model=RunLogsResponse, tags=["runs"])
def get_run_logs(
    run_id: str,
    store: Annotated[SQLiteRunStore, Depends(get_run_store)],
) -> RunLogsResponse:
    """Return derived agent outputs and quality gate logs for a workflow run."""
    record = _get_record_or_404(store, run_id)
    return RunLogsResponse(run_id=record.run_id, logs=_build_run_logs(record.state))


def _record_to_response(record: StoredRun) -> RunResponse:
    return RunResponse(
        run_id=record.run_id,
        status=record.status,
        repository_path=record.repository_path,
        feature_request=record.feature_request,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        state=record.state,
    )


def _get_record_or_404(store: SQLiteRunStore, run_id: str) -> StoredRun:
    try:
        return store.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        ) from exc


def _build_run_logs(state: AgentState) -> list[RunLogEntry]:
    logs: list[RunLogEntry] = [
        RunLogEntry(
            source="workflow",
            message=f"Run status: {state.final_status}",
            details={"iterations": state.iteration_count},
        )
    ]

    if state.repository_summary:
        logs.append(
            RunLogEntry(
                source="repository",
                message="Repository context loaded.",
                details={"summary": state.repository_summary},
            )
        )

    if state.task_list is not None:
        logs.append(
            RunLogEntry(
                source="planner",
                message=f"Planner produced {len(state.task_list.tasks)} task(s).",
                details={"tasks": state.task_list.model_dump(mode="json")},
            )
        )

    if state.architecture_plan is not None:
        logs.append(
            RunLogEntry(
                source="architect",
                message="Architect produced a design plan.",
                details=state.architecture_plan.model_dump(mode="json"),
            )
        )

    if state.changed_files or state.patch or state.diff:
        logs.append(
            RunLogEntry(
                source="coder",
                message=f"Code changes touched {len(state.changed_files)} file(s).",
                details={
                    "changed_files": state.changed_files,
                    "has_patch": state.patch is not None,
                    "has_diff": state.diff is not None,
                },
            )
        )

    for index, test_result in enumerate(state.test_results, start=1):
        logs.append(
            RunLogEntry(
                source="pytest",
                message=f"Pytest run {index} {'passed' if test_result.success else 'failed'}.",
                details=test_result.model_dump(mode="json"),
            )
        )

    static_results = [
        *state.lint_results,
        *state.type_check_results,
        *state.security_results,
    ]
    for result in static_results:
        outcome = "skipped" if result.skipped else "passed" if result.success else "failed"
        logs.append(
            RunLogEntry(
                source=result.tool,
                message=f"{result.tool} {outcome}.",
                details=result.model_dump(mode="json"),
            )
        )

    if state.review_result is not None:
        logs.append(
            RunLogEntry(
                source="reviewer",
                message=state.review_result.summary,
                details=state.review_result.model_dump(mode="json"),
            )
        )

    return logs
