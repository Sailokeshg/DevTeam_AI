# DevTeam AI Demo Script

Use this script for a recruiter screen, portfolio walkthrough, or interview demo.

## Setup

1. Start Ollama and pull the configured model.

```bash
ollama serve
ollama pull llama3.1
```

2. Install project dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "backend[dev,ui]"
```

3. Start the backend.

```bash
cd backend
uvicorn app.main:app --reload
```

4. Start the dashboard in another terminal.

```bash
streamlit run ui/streamlit_app.py
```

## Demo Flow

1. Open the Streamlit dashboard.
2. Click `Check health` to show the FastAPI backend is reachable.
3. Enter a local repository path, such as `examples/fastapi-demo-app`.
4. Enter a feature request:

```text
Add a /ping endpoint that returns {"message": "pong"} and include pytest coverage.
```

5. Start the run and narrate the workflow:

- Planner converts the request into typed tasks.
- Architect identifies impacted files, risks, and testing strategy.
- Coder proposes a unified diff instead of directly mutating unrelated files.
- Tester adds pytest coverage.
- Quality gates run pytest, Ruff, mypy, Bandit, and optional Semgrep.
- Reviewer approves or routes the run back for repair.

6. Show the final dashboard tabs:

- Overview: run status and timeline.
- Agents: planner tasks and architecture plan.
- Diff: patch generated for the repo.
- Quality: pytest and static-analysis output.
- Review: reviewer approval and issues.

7. Explain safety design:

- Path-safe file access.
- Patch-based code changes.
- Docker sandbox runner for commands.
- Token-safe GitHub integration.

## Interview Talking Points

- The project models real engineering workflow rather than just chat completion.
- Agent outputs are typed and validated with Pydantic.
- LangGraph makes the repair loop inspectable and testable.
- Tests use fake providers and temporary repositories, so CI does not require Ollama.
- The implementation intentionally separates planning, architecture, coding, testing, review, tools, storage, and UI.

## Fallback Demo

If Ollama is not available, show the test suite and dashboard with an existing saved run or mocked API response. The backend logic is covered by deterministic tests that do not depend on a real LLM.
