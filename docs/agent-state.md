# Agent State

`AgentState` is the shared state object that moves through the DevTeam AI workflow. Each agent reads the fields it needs, adds its own structured output, and leaves enough context for later agents to validate or repair the implementation.

## Lifecycle

1. A run starts with `user_request` and `repository_path`.
2. Repository inspection adds `repository_summary`.
3. The Planner Agent adds `task_list`.
4. The Architect Agent adds `architecture_plan`.
5. The Coder Agent adds `changed_files`, `code_changes`, `patch`, and `diff`.
6. The Tester Agent and quality tools add `test_results`, `lint_results`, `type_check_results`, and `security_results`.
7. The Reviewer Agent adds `review_result`.
8. The workflow updates `iteration_count` and `final_status`.

## Key Models

- `Task` captures a single unit of planned work with an id, title, description, type, dependencies, and acceptance criteria.
- `TaskList` validates that task ids are unique, dependencies reference known tasks, and the dependency graph has no cycles.
- `ArchitecturePlan` captures impacted files, design choices, risks, and testing strategy.
- `CodeChange` summarizes a focused file change and can include a diff fragment.
- `TestResult` captures pytest command status, counts, failed test names, output, and duration.
- `StaticAnalysisResult` captures lint, format, type-check, security, or static-analysis tool output.
- `ReviewIssue` and `ReviewResult` capture structured reviewer feedback and the next recommended action.

## Status Values

`final_status` starts as `pending`, moves to `running` during orchestration, and ends as one of `approved`, `rejected`, `failed`, or `max_iterations`.

This model is intentionally explicit so API responses, dashboard displays, persistence, and future LangGraph state all share the same contract.
