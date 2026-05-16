"""Task planning schemas used by the Planner Agent and workflow state."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TaskType = Literal[
    "feature",
    "bugfix",
    "test",
    "refactor",
    "documentation",
    "analysis",
    "security",
    "infrastructure",
]


class Task(BaseModel):
    """A single actionable task created from a user feature request."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: NonEmptyStr
    title: NonEmptyStr
    description: NonEmptyStr
    type: TaskType
    dependencies: list[NonEmptyStr]
    acceptance_criteria: list[NonEmptyStr] = Field(min_length=1)


class TaskList(BaseModel):
    """A validated collection of tasks with dependency relationships."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tasks: list[Task] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dependencies(self) -> Self:
        """Ensure task dependencies reference known tasks and do not form cycles."""
        task_ids: set[str] = set()
        duplicate_ids: set[str] = set()

        for task in self.tasks:
            if task.id in task_ids:
                duplicate_ids.add(task.id)
            task_ids.add(task.id)

        if duplicate_ids:
            duplicates = ", ".join(sorted(duplicate_ids))
            raise ValueError(f"Task ids must be unique: {duplicates}")

        for task in self.tasks:
            if task.id in task.dependencies:
                raise ValueError(f"Task {task.id} cannot depend on itself")

            unknown_dependencies = sorted(set(task.dependencies) - task_ids)
            if unknown_dependencies:
                unknown = ", ".join(unknown_dependencies)
                raise ValueError(f"Task {task.id} has unknown dependencies: {unknown}")

        graph = {task.id: task.dependencies for task in self.tasks}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            if task_id in visiting:
                raise ValueError("Task dependencies cannot contain cycles")

            visiting.add(task_id)
            for dependency_id in graph[task_id]:
                visit(dependency_id)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in graph:
            visit(task_id)

        return self
