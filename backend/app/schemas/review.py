"""Reviewer Agent feedback schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.task import NonEmptyStr

ReviewSeverity = Literal["info", "low", "medium", "high", "critical"]
RecommendedAction = Literal["approve", "revise_code", "revise_tests", "rerun_checks", "stop"]


class ReviewIssue(BaseModel):
    """A single actionable review finding."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    severity: ReviewSeverity
    message: NonEmptyStr
    file_path: NonEmptyStr | None = None
    line: int | None = Field(default=None, ge=1)
    suggested_fix: NonEmptyStr | None = None
    source: NonEmptyStr | None = None


class ReviewResult(BaseModel):
    """Structured Reviewer Agent decision."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    approved: bool
    issues: list[ReviewIssue]
    recommended_next_action: RecommendedAction
    summary: NonEmptyStr
