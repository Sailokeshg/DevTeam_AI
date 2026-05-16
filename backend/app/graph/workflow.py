"""LangGraph workflow orchestration and Phase 8 repair-loop compatibility."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from app.agents import (
    ArchitectAgent,
    CoderAgent,
    PlannerAgent,
    RelevantFile,
    ReviewerAgent,
    TesterAgent,
)
from app.llm import LLMProvider, create_default_llm_provider
from app.schemas.agent_state import AgentState, StaticAnalysisResult
from app.schemas.review import ReviewIssue, ReviewResult
from app.tools import (
    FileToolError,
    apply_unified_diff,
    get_diff,
    read_file,
    summarize_repository_tree,
)
from app.tools.static_analysis import QualityGateResult, run_all_quality_gates

WorkflowRoute = Literal["coder", "tester", "run_quality_gates", "finalize"]
WorkflowNodeName = Literal[
    "load_repo_context",
    "planner",
    "architect",
    "coder",
    "tester",
    "run_quality_gates",
    "reviewer",
    "finalize",
]


class DevTeamWorkflowState(TypedDict):
    """LangGraph state shared across DevTeam AI workflow nodes."""

    agent_state: AgentState
    max_iterations: int
    quality_gate_passed: bool
    workflow_events: list[str]


WorkflowStateUpdater = Callable[[AgentState], AgentState]
RepairNodeRunner = Callable[[AgentState, str], AgentState]
RepairRunner = RepairNodeRunner
QualityGateRunner = Callable[[AgentState], QualityGateResult]
ReviewRunner = Callable[[AgentState], ReviewResult]


@dataclass(slots=True)
class WorkflowServices:
    """Injectable services used by the LangGraph workflow nodes."""

    load_repo_context: WorkflowStateUpdater
    planner: WorkflowStateUpdater
    architect: WorkflowStateUpdater
    coder: RepairNodeRunner
    tester: RepairNodeRunner
    quality_gate_runner: QualityGateRunner
    reviewer: ReviewRunner


class WorkflowExecutionError(ValueError):
    """Raised when the LangGraph workflow cannot continue safely."""


class RepairLoopError(ValueError):
    """Raised when the manual repair loop is configured incorrectly."""


def create_default_workflow_services(
    *,
    llm_provider: LLMProvider | None = None,
    include_semgrep: bool = False,
) -> WorkflowServices:
    """Create production services for the LangGraph workflow."""
    active_provider = llm_provider or create_default_llm_provider()
    planner_agent = PlannerAgent(active_provider)
    architect_agent = ArchitectAgent(active_provider)
    coder_agent = CoderAgent(active_provider)
    tester_agent = TesterAgent(active_provider)
    reviewer_agent = ReviewerAgent(active_provider)

    return WorkflowServices(
        load_repo_context=_default_load_repo_context,
        planner=lambda state: _default_plan(state, planner_agent),
        architect=lambda state: _default_design(state, architect_agent),
        coder=lambda state, feedback: _default_code(state, coder_agent),
        tester=lambda state, feedback: _default_test(state, tester_agent, feedback),
        quality_gate_runner=lambda state: run_all_quality_gates(
            state.repository_path,
            include_semgrep=include_semgrep,
        ),
        reviewer=reviewer_agent.review_state,
    )


def build_devteam_workflow_graph(services: WorkflowServices) -> Any:
    """Build the LangGraph state machine for DevTeam AI."""
    graph = StateGraph(DevTeamWorkflowState)

    graph.add_node(
        "load_repo_context",
        cast(Any, _make_state_node("load_repo_context", services.load_repo_context)),
    )
    graph.add_node("planner", cast(Any, _make_state_node("planner", services.planner)))
    graph.add_node("architect", cast(Any, _make_state_node("architect", services.architect)))
    graph.add_node("coder", cast(Any, _make_repair_node("coder", services.coder)))
    graph.add_node("tester", cast(Any, _make_repair_node("tester", services.tester)))
    graph.add_node(
        "run_quality_gates",
        cast(Any, _make_quality_gate_node(services.quality_gate_runner)),
    )
    graph.add_node("reviewer", cast(Any, _make_reviewer_node(services.reviewer)))
    graph.add_node("finalize", cast(Any, _finalize_node))

    graph.add_edge(START, "load_repo_context")
    graph.add_edge("load_repo_context", "planner")
    graph.add_edge("planner", "architect")
    graph.add_edge("architect", "coder")
    graph.add_edge("coder", "tester")
    graph.add_edge("tester", "run_quality_gates")
    graph.add_edge("run_quality_gates", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        route_after_review,
        {
            "coder": "coder",
            "tester": "tester",
            "run_quality_gates": "run_quality_gates",
            "finalize": "finalize",
        },
    )
    graph.add_edge("finalize", END)

    return graph.compile()


def run_workflow_with_services(
    initial_state: AgentState,
    *,
    services: WorkflowServices,
    max_iterations: int = 3,
) -> AgentState:
    """Run the LangGraph workflow with explicitly provided services."""
    if max_iterations < 1:
        raise WorkflowExecutionError("max_iterations must be at least 1")

    graph = build_devteam_workflow_graph(services)
    result = graph.invoke(
        {
            "agent_state": initial_state,
            "max_iterations": max_iterations,
            "quality_gate_passed": False,
            "workflow_events": [],
        },
        {"recursion_limit": max_iterations * 8 + 16},
    )
    return _coerce_agent_state(result["agent_state"])


def run_devteam_workflow(
    *,
    repo_path: str,
    feature_request: str,
    llm_provider: LLMProvider | None = None,
    max_iterations: int = 3,
    include_semgrep: bool = False,
) -> AgentState:
    """Run the complete LangGraph workflow for a local repo and feature request."""
    services = create_default_workflow_services(
        llm_provider=llm_provider,
        include_semgrep=include_semgrep,
    )
    initial_state = AgentState(user_request=feature_request, repository_path=repo_path)
    return run_workflow_with_services(
        initial_state,
        services=services,
        max_iterations=max_iterations,
    )


def route_after_review(state: DevTeamWorkflowState) -> WorkflowRoute:
    """Route the graph after reviewer output."""
    agent_state = _coerce_agent_state(state["agent_state"])
    review_result = agent_state.review_result

    if review_result is None:
        return "finalize"
    if review_result.approved and state["quality_gate_passed"]:
        return "finalize"
    if review_result.recommended_next_action == "stop":
        return "finalize"
    if agent_state.iteration_count >= state["max_iterations"]:
        return "finalize"
    if review_result.recommended_next_action == "rerun_checks":
        return "run_quality_gates"
    if _should_route_to_tester_state(agent_state, review_result):
        return "tester"
    if _should_route_to_coder_state(agent_state, review_result):
        return "coder"

    return "coder"


def _make_state_node(
    name: WorkflowNodeName,
    runner: WorkflowStateUpdater,
) -> Callable[[DevTeamWorkflowState], dict[str, object]]:
    def node(state: DevTeamWorkflowState) -> dict[str, object]:
        agent_state = runner(_coerce_agent_state(state["agent_state"]).model_copy(deep=True))
        return _state_update(state, agent_state, name)

    return node


def _make_repair_node(
    name: Literal["coder", "tester"],
    runner: RepairNodeRunner,
) -> Callable[[DevTeamWorkflowState], dict[str, object]]:
    def node(state: DevTeamWorkflowState) -> dict[str, object]:
        agent_state = _coerce_agent_state(state["agent_state"]).model_copy(deep=True)
        feedback = build_repair_feedback(agent_state)
        repaired_state = runner(agent_state, feedback)
        return _state_update(state, repaired_state, name)

    return node


def _make_quality_gate_node(
    runner: QualityGateRunner,
) -> Callable[[DevTeamWorkflowState], dict[str, object]]:
    def node(state: DevTeamWorkflowState) -> dict[str, object]:
        agent_state = _coerce_agent_state(state["agent_state"]).model_copy(deep=True)
        agent_state.iteration_count += 1
        quality_result = runner(agent_state)
        _record_quality_gate_results(agent_state, quality_result)
        return {
            **_state_update(state, agent_state, "run_quality_gates"),
            "quality_gate_passed": quality_result.all_passed,
        }

    return node


def _make_reviewer_node(
    runner: ReviewRunner,
) -> Callable[[DevTeamWorkflowState], dict[str, object]]:
    def node(state: DevTeamWorkflowState) -> dict[str, object]:
        agent_state = _coerce_agent_state(state["agent_state"]).model_copy(deep=True)
        agent_state.review_result = runner(agent_state)
        return _state_update(state, agent_state, "reviewer")

    return node


def _finalize_node(state: DevTeamWorkflowState) -> dict[str, object]:
    agent_state = _coerce_agent_state(state["agent_state"]).model_copy(deep=True)
    review_result = agent_state.review_result

    if review_result is not None and review_result.approved and state["quality_gate_passed"]:
        agent_state.final_status = "approved"
    elif review_result is not None and review_result.recommended_next_action == "stop":
        agent_state.final_status = "rejected"
    elif agent_state.iteration_count >= state["max_iterations"]:
        agent_state.final_status = "max_iterations"
    elif review_result is None:
        agent_state.final_status = "failed"
    else:
        agent_state.final_status = "failed"

    return _state_update(state, agent_state, "finalize")


def _state_update(
    state: DevTeamWorkflowState,
    agent_state: AgentState,
    event: WorkflowNodeName,
) -> dict[str, object]:
    return {
        "agent_state": agent_state,
        "workflow_events": [*state["workflow_events"], event],
    }


def _default_load_repo_context(state: AgentState) -> AgentState:
    summary = summarize_repository_tree(state.repository_path)
    extensions = ", ".join(
        f"{extension}: {count}" for extension, count in summary.file_extensions.items()
    )
    state.repository_summary = (
        f"Repository tree:\n{summary.tree}\n\n"
        f"Files: {summary.total_files}\n"
        f"Directories: {summary.total_directories}\n"
        f"Extensions: {extensions or 'none'}"
    )
    return state


def _default_plan(state: AgentState, planner_agent: PlannerAgent) -> AgentState:
    state.task_list = planner_agent.plan(
        user_request=state.user_request,
        repository_summary=state.repository_summary,
    )
    return state


def _default_design(state: AgentState, architect_agent: ArchitectAgent) -> AgentState:
    if state.task_list is None:
        raise WorkflowExecutionError("Planner output is required before architect node")

    state.architecture_plan = architect_agent.design(
        user_request=state.user_request,
        repository_summary=state.repository_summary or "",
        task_list=state.task_list,
    )
    return state


def _default_code(state: AgentState, coder_agent: CoderAgent) -> AgentState:
    if state.task_list is None or state.architecture_plan is None:
        raise WorkflowExecutionError(
            "Task list and architecture plan are required before coder node"
        )

    relevant_files = _load_relevant_files(state)
    patch = coder_agent.generate_patch(
        user_request=state.user_request,
        task_list=state.task_list,
        architecture_plan=state.architecture_plan,
        relevant_files=relevant_files,
    )
    return _apply_patch_to_state(state, patch)


def _default_test(state: AgentState, tester_agent: TesterAgent, feedback: str) -> AgentState:
    if state.task_list is None or state.architecture_plan is None:
        raise WorkflowExecutionError(
            "Task list and architecture plan are required before tester node"
        )

    relevant_files = _load_relevant_files(state)
    patch = tester_agent.generate_test_patch(
        user_request=state.user_request,
        task_list=state.task_list,
        architecture_plan=state.architecture_plan,
        relevant_files=relevant_files,
        implementation_diff=feedback or state.diff or state.patch,
    )
    return _apply_patch_to_state(state, patch)


def _apply_patch_to_state(state: AgentState, patch: str) -> AgentState:
    result = apply_unified_diff(state.repository_path, patch)
    state.patch = _append_text_block(state.patch, patch)
    state.changed_files = _merge_unique(state.changed_files, result.changed_files)
    state.diff = get_diff(state.repository_path)
    return state


def _load_relevant_files(state: AgentState) -> list[RelevantFile]:
    paths = set(state.changed_files)
    if state.architecture_plan is not None:
        paths.update(state.architecture_plan.impacted_files)

    relevant_files: list[RelevantFile] = []
    for path in sorted(paths):
        try:
            file_result = read_file(state.repository_path, path)
        except FileToolError:
            continue
        relevant_files.append(RelevantFile(path=file_result.path, content=file_result.content))

    return relevant_files


def _should_route_to_tester_state(
    state: AgentState,
    review_result: ReviewResult,
) -> bool:
    latest_test_result = state.test_results[-1] if state.test_results else None
    return review_result.recommended_next_action == "revise_tests" or (
        latest_test_result is not None and not latest_test_result.success
    )


def _should_route_to_coder_state(
    state: AgentState,
    review_result: ReviewResult,
) -> bool:
    static_results = [*state.lint_results, *state.type_check_results, *state.security_results]
    return review_result.recommended_next_action == "revise_code" or _has_static_failures(
        static_results
    )


def _coerce_agent_state(value: AgentState | dict[str, object]) -> AgentState:
    if isinstance(value, AgentState):
        return value
    return AgentState.model_validate(value)


def _append_text_block(existing: str | None, new_value: str) -> str:
    if not existing:
        return new_value
    return f"{existing.rstrip()}\n\n{new_value.lstrip()}"


def _merge_unique(existing: list[str], new_values: list[str]) -> list[str]:
    merged = list(existing)
    for value in new_values:
        if value not in merged:
            merged.append(value)
    return merged


def run_repair_loop(
    initial_state: AgentState,
    *,
    quality_gate_runner: QualityGateRunner,
    reviewer: ReviewRunner,
    coder_repair: RepairRunner,
    tester_repair: RepairRunner,
    max_iterations: int = 3,
) -> AgentState:
    """Run a simple review/repair loop until approved, rejected, or exhausted."""
    if max_iterations < 1:
        raise RepairLoopError("max_iterations must be at least 1")

    state = initial_state.model_copy(deep=True)
    state.final_status = "running"

    for iteration in range(1, max_iterations + 1):
        state.iteration_count = iteration
        quality_result = quality_gate_runner(state)
        _record_quality_gate_results(state, quality_result)

        review_result = reviewer(state)
        state.review_result = review_result

        if review_result.approved and quality_result.all_passed:
            state.final_status = "approved"
            return state

        if review_result.recommended_next_action == "stop":
            state.final_status = "rejected"
            return state

        if iteration == max_iterations:
            state.final_status = "max_iterations"
            return state

        feedback = build_repair_feedback(state)
        if _should_route_to_tester(quality_result, review_result):
            state = tester_repair(state, feedback)
        elif _should_route_to_coder(quality_result, review_result):
            state = coder_repair(state, feedback)
        elif review_result.recommended_next_action == "rerun_checks":
            continue
        else:
            state.final_status = "rejected"
            return state

        state.final_status = "running"

    state.final_status = "max_iterations"
    return state


def build_repair_feedback(state: AgentState) -> str:
    """Build concise feedback to send back to a repair agent."""
    sections = []

    if state.review_result is not None:
        sections.append(f"Review summary: {state.review_result.summary}")
        issue_lines = [_format_review_issue(issue) for issue in state.review_result.issues]
        if issue_lines:
            sections.append("Review issues:\n" + "\n".join(issue_lines))

    if state.test_results:
        latest_test_result = state.test_results[-1]
        if not latest_test_result.success:
            failed_names = ", ".join(latest_test_result.failed_tests) or "unknown"
            sections.append(
                "Test failures:\n"
                f"failed_count={latest_test_result.failed_count}; failed_tests={failed_names}\n"
                f"{latest_test_result.error_output or latest_test_result.output}"
            )

    static_failures = [
        result
        for result in [*state.lint_results, *state.type_check_results, *state.security_results]
        if not result.success and not result.skipped
    ]
    if static_failures:
        static_failure_text = "\n".join(
            _format_static_failure(result) for result in static_failures
        )
        sections.append(f"Static-analysis failures:\n{static_failure_text}")

    return "\n\n".join(section for section in sections if section).strip()


def _record_quality_gate_results(state: AgentState, quality_result: QualityGateResult) -> None:
    state.test_results = [quality_result.test_result]
    state.lint_results = []
    state.type_check_results = []
    state.security_results = []

    for result in quality_result.static_analysis_results:
        if result.tool in {"ruff", "ruff-format"}:
            state.lint_results.append(result)
        elif result.tool == "mypy":
            state.type_check_results.append(result)
        elif result.tool in {"bandit", "semgrep"}:
            state.security_results.append(result)
        else:
            state.lint_results.append(result)


def _should_route_to_tester(
    quality_result: QualityGateResult,
    review_result: ReviewResult,
) -> bool:
    return (
        not quality_result.test_result.success
        or review_result.recommended_next_action == "revise_tests"
    )


def _should_route_to_coder(
    quality_result: QualityGateResult,
    review_result: ReviewResult,
) -> bool:
    return (
        _has_static_failures(quality_result.static_analysis_results)
        or review_result.recommended_next_action == "revise_code"
    )


def _has_static_failures(results: list[StaticAnalysisResult]) -> bool:
    return any(not result.success and not result.skipped for result in results)


def _format_review_issue(issue: ReviewIssue) -> str:
    location = f" ({issue.file_path}:{issue.line})" if issue.file_path and issue.line else ""
    source = f" [{issue.source}]" if issue.source else ""
    fix = f" Suggested fix: {issue.suggested_fix}" if issue.suggested_fix else ""
    return f"- {issue.severity}{source}{location}: {issue.message}{fix}"


def _format_static_failure(result: StaticAnalysisResult) -> str:
    issue_text = "; ".join(result.issues) if result.issues else result.error_output or result.output
    return f"- {result.tool}: {issue_text}"
