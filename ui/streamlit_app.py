"""Streamlit dashboard for DevTeam AI workflow runs."""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

DEFAULT_API_BASE_URL = os.getenv("DEVTEAM_AI_API_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT_SECONDS = 300.0


RunData = dict[str, Any]


def main() -> None:
    """Render the DevTeam AI dashboard."""
    configure_page()
    render_header()

    api_base_url = render_sidebar()
    run_data = render_run_controls(api_base_url)

    if run_data is None:
        render_empty_state()
        return

    render_dashboard(api_base_url, run_data)


def configure_page() -> None:
    st.set_page_config(
        page_title="DevTeam AI Dashboard",
        page_icon="DT",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
            :root {
                --ink: #18211f;
                --sand: #f5efe2;
                --clay: #c96f4a;
                --moss: #2f604f;
                --blue: #244b7a;
                --panel: rgba(255, 252, 244, 0.92);
            }
            .stApp {
                color: var(--ink);
                background:
                    radial-gradient(circle at 12% 15%, rgba(201, 111, 74, 0.22), transparent 34%),
                    radial-gradient(circle at 82% 6%, rgba(47, 96, 79, 0.20), transparent 30%),
                    linear-gradient(135deg, #fbf4e7 0%, #edf3ea 48%, #f5efe2 100%);
            }
            .hero-card {
                border: 1px solid rgba(24, 33, 31, 0.12);
                border-radius: 28px;
                padding: 2rem;
                background: var(--panel);
                box-shadow: 0 24px 80px rgba(44, 35, 22, 0.12);
            }
            .eyebrow {
                color: var(--clay);
                font-size: 0.78rem;
                font-weight: 800;
                letter-spacing: 0.16em;
                text-transform: uppercase;
            }
            .hero-title {
                font-family: Georgia, 'Times New Roman', serif;
                font-size: clamp(2.4rem, 5vw, 4.8rem);
                line-height: 0.92;
                margin: 0.35rem 0 0.8rem;
            }
            .hero-copy {
                color: rgba(24, 33, 31, 0.74);
                font-size: 1.05rem;
                max-width: 820px;
            }
            .status-pill {
                display: inline-block;
                padding: 0.35rem 0.65rem;
                border-radius: 999px;
                background: rgba(47, 96, 79, 0.12);
                color: var(--moss);
                font-weight: 700;
                font-size: 0.85rem;
            }
            .timeline-item {
                border-left: 3px solid rgba(201, 111, 74, 0.75);
                padding: 0.15rem 0 0.85rem 0.85rem;
                margin-left: 0.35rem;
            }
            .timeline-source {
                color: var(--blue);
                font-weight: 800;
                text-transform: uppercase;
                font-size: 0.72rem;
                letter-spacing: 0.10em;
            }
            .small-muted {
                color: rgba(24, 33, 31, 0.62);
                font-size: 0.92rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.markdown(
        """
        <div class="hero-card">
            <div class="eyebrow">Multi-agent software delivery</div>
            <div class="hero-title">DevTeam AI</div>
            <div class="hero-copy">
                Turn a feature request into a visible engineering workflow: planning,
                architecture, code patches, pytest results, static analysis, and reviewer feedback.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")


def render_sidebar() -> str:
    with st.sidebar:
        st.header("Backend")
        api_base_url = st.text_input("API base URL", value=DEFAULT_API_BASE_URL).rstrip("/")
        st.caption("Start the FastAPI backend first, then trigger or inspect runs here.")

        if st.button("Check health", use_container_width=True):
            try:
                health = api_get(api_base_url, "/health")
            except httpx.HTTPError as exc:
                st.error(f"Backend health check failed: {exc}")
            else:
                st.success(f"Backend status: {health.get('status', 'unknown')}")

        st.divider()
        st.header("Demo flow")
        st.markdown(
            """
            1. Run the backend API.
            2. Enter a local repo path.
            3. Describe the feature request.
            4. Review the generated run timeline and diff.
            """
        )

    return api_base_url


def render_run_controls(api_base_url: str) -> RunData | None:
    if "run_data" not in st.session_state:
        st.session_state["run_data"] = None

    left, right = st.columns([1.4, 1.0], gap="large")

    with left:
        st.subheader("Start A Run")
        with st.form("start-run-form"):
            repository_path = st.text_input(
                "Local repository path",
                placeholder="/Users/you/projects/example-app",
            )
            feature_request = st.text_area(
                "Feature request",
                placeholder=(
                    "Add input validation for the create-user endpoint and cover edge cases."
                ),
                height=130,
            )
            max_iterations = st.slider("Max iterations", min_value=1, max_value=10, value=3)
            submitted = st.form_submit_button("Start synchronous run", use_container_width=True)

        if submitted:
            payload = {
                "repository_path": repository_path,
                "feature_request": feature_request,
                "max_iterations": max_iterations,
            }
            with st.spinner("The agents are working. This can take a while for real LLM runs..."):
                try:
                    st.session_state["run_data"] = api_post(api_base_url, "/runs", payload)
                except httpx.HTTPStatusError as exc:
                    st.error(f"Run failed: {format_http_error(exc)}")
                except httpx.HTTPError as exc:
                    st.error(f"Could not reach backend: {exc}")

    with right:
        st.subheader("Inspect Existing Run")
        run_id = st.text_input("Run ID", placeholder="Paste a run id from POST /runs")
        if st.button("Load run", use_container_width=True):
            if not run_id.strip():
                st.warning("Enter a run id first.")
            else:
                try:
                    st.session_state["run_data"] = api_get(api_base_url, f"/runs/{run_id.strip()}")
                except httpx.HTTPStatusError as exc:
                    st.error(f"Could not load run: {format_http_error(exc)}")
                except httpx.HTTPError as exc:
                    st.error(f"Could not reach backend: {exc}")

    return st.session_state.get("run_data")


def render_empty_state() -> None:
    st.info("Start a new run or load an existing run to see the agent timeline.")


def render_dashboard(api_base_url: str, run_data: RunData) -> None:
    state = get_state(run_data)
    run_id = str(run_data.get("run_id", ""))
    logs = load_run_logs(api_base_url, run_id)
    diff = load_run_diff(api_base_url, run_id) or str(state.get("diff") or "")

    render_status_band(run_data, state)

    tab_overview, tab_agents, tab_diff, tab_quality, tab_review = st.tabs(
        ["Overview", "Agents", "Diff", "Quality", "Review"]
    )

    with tab_overview:
        render_final_summary(run_data, state)
        render_timeline(logs)

    with tab_agents:
        render_task_list(state)
        render_architecture_plan(state)

    with tab_diff:
        render_diff(diff)

    with tab_quality:
        render_test_results(state)
        render_static_analysis_results(state)

    with tab_review:
        render_reviewer_feedback(state)


def render_status_band(run_data: RunData, state: RunData) -> None:
    status_text = str(run_data.get("status") or state.get("final_status") or "unknown")
    run_id = str(run_data.get("run_id") or "unknown")
    changed_files = state.get("changed_files") or []

    st.markdown(f'<span class="status-pill">{status_text}</span>', unsafe_allow_html=True)
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Run ID", run_id[:10] + ("..." if len(run_id) > 10 else ""))
    col_b.metric("Iterations", int(state.get("iteration_count") or 0))
    col_c.metric("Changed files", len(changed_files))
    col_d.metric("Tests", summarize_tests(state))


def render_final_summary(run_data: RunData, state: RunData) -> None:
    st.subheader("Final Summary")
    st.write(
        {
            "run_id": run_data.get("run_id"),
            "status": run_data.get("status"),
            "repository_path": run_data.get("repository_path"),
            "feature_request": run_data.get("feature_request"),
            "created_at": run_data.get("created_at"),
            "updated_at": run_data.get("updated_at"),
        }
    )

    changed_files = state.get("changed_files") or []
    if changed_files:
        st.write("Changed files")
        st.code("\n".join(str(path) for path in changed_files), language="text")


def render_timeline(logs: list[RunData]) -> None:
    st.subheader("Agent Timeline")
    if not logs:
        st.caption("No logs are available yet.")
        return

    for entry in logs:
        source = entry.get("source", "workflow")
        message = entry.get("message", "")
        st.markdown(
            f"""
            <div class="timeline-item">
                <div class="timeline-source">{source}</div>
                <div>{message}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_task_list(state: RunData) -> None:
    st.subheader("Planner Task List")
    tasks = (state.get("task_list") or {}).get("tasks") or []
    if not tasks:
        st.caption("No planner tasks were captured.")
        return

    for task in tasks:
        with st.expander(f"{task.get('id', 'task')} · {task.get('title', 'Untitled task')}"):
            st.write(task.get("description", ""))
            st.write(f"Type: `{task.get('type', 'unknown')}`")
            st.write("Dependencies")
            st.write(task.get("dependencies") or [])
            st.write("Acceptance criteria")
            st.write(task.get("acceptance_criteria") or [])


def render_architecture_plan(state: RunData) -> None:
    st.subheader("Architect Design")
    plan = state.get("architecture_plan") or {}
    if not plan:
        st.caption("No architecture plan was captured.")
        return

    st.write(plan.get("summary", ""))
    col_a, col_b = st.columns(2)
    col_a.write("Impacted files")
    col_a.write(plan.get("impacted_files") or [])
    col_a.write("Design choices")
    col_a.write(plan.get("design_choices") or [])
    col_b.write("Risks")
    col_b.write(plan.get("risks") or [])
    col_b.write("Testing strategy")
    col_b.write(plan.get("testing_strategy") or [])


def render_diff(diff: str) -> None:
    st.subheader("Code Diff")
    if not diff:
        st.caption("No diff was captured for this run.")
        return
    st.code(diff, language="diff")


def render_test_results(state: RunData) -> None:
    st.subheader("Pytest Results")
    test_results = state.get("test_results") or []
    if not test_results:
        st.caption("No pytest results were captured.")
        return

    for index, result in enumerate(test_results, start=1):
        label = "passed" if result.get("success") else "failed"
        with st.expander(f"Pytest run {index}: {label}", expanded=index == len(test_results)):
            cols = st.columns(3)
            cols[0].metric("Passed", int(result.get("passed_count") or 0))
            cols[1].metric("Failed", int(result.get("failed_count") or 0))
            cols[2].metric("Skipped", int(result.get("skipped_count") or 0))
            if result.get("failed_tests"):
                st.write("Failed tests")
                st.write(result.get("failed_tests"))
            output = result.get("error_output") or result.get("output")
            if output:
                st.code(str(output), language="text")


def render_static_analysis_results(state: RunData) -> None:
    st.subheader("Static Analysis")
    results = [
        *(state.get("lint_results") or []),
        *(state.get("type_check_results") or []),
        *(state.get("security_results") or []),
    ]
    if not results:
        st.caption("No static-analysis results were captured.")
        return

    for result in results:
        outcome = (
            "skipped" if result.get("skipped") else "passed" if result.get("success") else "failed"
        )
        with st.expander(f"{result.get('tool', 'tool')}: {outcome}"):
            st.write(f"Command: `{result.get('command', '')}`")
            if result.get("issues"):
                st.write(result.get("issues"))
            output = result.get("error_output") or result.get("output")
            if output:
                st.code(str(output), language="text")


def render_reviewer_feedback(state: RunData) -> None:
    st.subheader("Reviewer Feedback")
    review = state.get("review_result")
    if not review:
        st.caption("No reviewer result was captured.")
        return

    st.write(review.get("summary", ""))
    st.write(f"Approved: `{review.get('approved')}`")
    st.write(f"Recommended next action: `{review.get('recommended_next_action')}`")

    issues = review.get("issues") or []
    if issues:
        st.write("Issues")
        st.dataframe(issues, use_container_width=True)
    else:
        st.success("No reviewer issues reported.")


def load_run_logs(api_base_url: str, run_id: str) -> list[RunData]:
    if not run_id:
        return []
    try:
        response = api_get(api_base_url, f"/runs/{run_id}/logs")
    except httpx.HTTPError:
        return []
    return list(response.get("logs") or [])


def load_run_diff(api_base_url: str, run_id: str) -> str:
    if not run_id:
        return ""
    try:
        response = api_get(api_base_url, f"/runs/{run_id}/diff")
    except httpx.HTTPError:
        return ""
    return str(response.get("diff") or "")


def api_get(api_base_url: str, path: str) -> RunData:
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.get(f"{api_base_url}{path}")
        response.raise_for_status()
        return response.json()


def api_post(api_base_url: str, path: str, payload: RunData) -> RunData:
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.post(f"{api_base_url}{path}", json=payload)
        response.raise_for_status()
        return response.json()


def get_state(run_data: RunData) -> RunData:
    state = run_data.get("state")
    return state if isinstance(state, dict) else {}


def summarize_tests(state: RunData) -> str:
    test_results = state.get("test_results") or []
    if not test_results:
        return "none"
    latest = test_results[-1]
    return "passed" if latest.get("success") else "failed"


def format_http_error(exc: httpx.HTTPStatusError) -> str:
    try:
        detail = exc.response.json().get("detail")
    except ValueError:
        detail = exc.response.text
    return f"{exc.response.status_code}: {detail}"


if __name__ == "__main__":
    main()
