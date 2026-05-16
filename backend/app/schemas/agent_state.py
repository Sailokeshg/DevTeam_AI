"""Shared workflow state schemas for DevTeam AI agent runs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.review import ReviewResult
from app.schemas.task import NonEmptyStr, TaskList

CodeChangeType = Literal["create", "modify", "delete", "rename"]
FinalStatus = Literal["pending", "running", "approved", "rejected", "failed", "max_iterations"]


class ArchitecturePlan(BaseModel):
    """Architect Agent design output for a requested implementation."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    summary: NonEmptyStr
    impacted_files: list[NonEmptyStr]
    design_choices: list[NonEmptyStr]
    risks: list[NonEmptyStr]
    testing_strategy: list[NonEmptyStr]


class CodeChange(BaseModel):
    """A focused source change proposed or applied by an agent."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    file_path: NonEmptyStr
    change_type: CodeChangeType
    description: NonEmptyStr
    diff: str | None = None


class TestResult(BaseModel):
    """Structured result from a pytest execution."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    command: NonEmptyStr
    success: bool
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    skipped_count: int = Field(default=0, ge=0)
    failed_tests: list[NonEmptyStr] = Field(default_factory=list)
    output: str = ""
    error_output: str = ""
    duration_seconds: float | None = Field(default=None, ge=0)


class StaticAnalysisResult(BaseModel):
    """Structured result from linting, type checking, or security scanning."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tool: NonEmptyStr
    command: NonEmptyStr
    success: bool
    skipped: bool = False
    issues: list[NonEmptyStr] = Field(default_factory=list)
    output: str = ""
    error_output: str = ""
    duration_seconds: float | None = Field(default=None, ge=0)


class AgentState(BaseModel):
    """Complete shared state passed through the multi-agent workflow."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    user_request: NonEmptyStr
    repository_path: NonEmptyStr
    repository_summary: str | None = None
    task_list: TaskList | None = None
    architecture_plan: ArchitecturePlan | None = None
    changed_files: list[NonEmptyStr] = Field(default_factory=list)
    code_changes: list[CodeChange] = Field(default_factory=list)
    patch: str | None = None
    diff: str | None = None
    test_results: list[TestResult] = Field(default_factory=list)
    lint_results: list[StaticAnalysisResult] = Field(default_factory=list)
    type_check_results: list[StaticAnalysisResult] = Field(default_factory=list)
    security_results: list[StaticAnalysisResult] = Field(default_factory=list)
    review_result: ReviewResult | None = None
    iteration_count: int = Field(default=0, ge=0)
    final_status: FinalStatus = "pending"
