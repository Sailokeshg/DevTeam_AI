# DevTeam AI

DevTeam AI is a multi-agent software development system that collaborates like a real software team. It accepts a feature request, analyzes a codebase, plans work, proposes architecture, generates code and tests, runs quality checks, and reviews results in an iterative loop.

## Architecture Summary

The project is split into:

- `backend/`: FastAPI service, agent logic, workflow orchestration, tools, schemas, and persistence.
- `ui/`: Streamlit dashboard for running and observing agent workflows.
- `prompts/`: Prompt templates for each agent role.
- `examples/`: Demo repositories used for local evaluation.
- `docs/`: Architecture notes, demo script, and resume-ready project points.

## Planned Phases

0. Project scaffold and developer setup
1. Core schemas and shared workflow state
2. LLM provider abstraction with Ollama
3. Prompt templates and Planner/Architect agents
4. Repository inspection and file tools
5. Coder agent with patch-based changes
6. Tester agent and pytest runner
7. Static analysis tools
8. Reviewer agent and repair loop
9. LangGraph workflow orchestration
10. FastAPI endpoints for run management
11. Streamlit dashboard
12. Docker sandbox execution
13. Git and GitHub integration
14. CI/CD and portfolio polish
15. Evaluation and example runs

## Local Setup (Phase 0)

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -e "backend[dev]"
```

### 3. Run the backend API

```bash
cd backend
uvicorn app.main:app --reload
```

API health check:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status": "ok"}
```

## Quality Checks (Phase 0)

From the `backend/` directory:

```bash
cd backend
pytest
ruff check .
mypy app
```

## Current Status

Phase 0 scaffolding is implemented:

- FastAPI backend skeleton
- `GET /health` endpoint
- baseline pytest coverage
- Ruff and mypy configuration
- starter project documentation and conventions

Phase 1 core schemas are implemented:

- Planner task and task-list models
- Architecture, code-change, test-result, static-analysis, review, and agent-state models
- Validation tests for schema behavior
- [Agent state documentation](docs/agent-state.md)
