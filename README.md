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

## Local Setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -e "backend[dev]"
```

To include the Streamlit dashboard dependencies:

```bash
pip install -e "backend[dev,ui]"
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

## Run API (Phase 10)

Phase 10 adds synchronous run-management endpoints backed by local SQLite storage.

Start a workflow run:

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "repository_path": "/absolute/path/to/local/repo",
    "feature_request": "Add a /ping endpoint with tests",
    "max_iterations": 3
  }'
```

Inspect saved run data:

```bash
curl http://127.0.0.1:8000/runs/<run_id>
curl http://127.0.0.1:8000/runs/<run_id>/diff
curl http://127.0.0.1:8000/runs/<run_id>/logs
```

Run history is stored in `.devteam-ai/runs.sqlite3` by default. Set
`DEVTEAM_AI_RUN_DB=/path/to/runs.sqlite3` to use a different SQLite database.

## Streamlit Dashboard (Phase 11)

Run the FastAPI backend in one terminal:

```bash
cd backend
uvicorn app.main:app --reload
```

Run the dashboard in a second terminal:

```bash
streamlit run ui/streamlit_app.py
```

The dashboard defaults to `http://127.0.0.1:8000`. Set
`DEVTEAM_AI_API_URL=http://host:port` or use the sidebar input to target a different backend.
It can start a new synchronous run or load an existing run id, then display the agent timeline,
planner tasks, architecture plan, code diff, pytest results, static-analysis results, reviewer
feedback, and final summary.

## Docker Sandbox (Phase 12)

Phase 12 adds a constrained Docker runner for test and quality-gate commands. Build the
sandbox image from the repository root:

```bash
docker build -f backend/Dockerfile.sandbox -t devteam-ai-sandbox:latest backend
```

The runner allows only these executables inside the sandbox:

- `pytest`
- `ruff`
- `mypy`
- `bandit`
- `semgrep`

Sandbox defaults:

- mounts only the selected repository at `/workspace`
- disables network access by default
- applies memory, CPU, and PID limits
- drops Linux capabilities and enables `no-new-privileges`
- runs with a read-only container filesystem and temporary writable cache directories
- rejects shell control operators, absolute paths, and path traversal outside `/workspace`

Example internal use:

```python
from app.tools.docker_runner import run_sandboxed_command

result = run_sandboxed_command("/absolute/path/to/repo", ["pytest", "-q"])
print(result.success, result.output)
```

Sandbox limitations:

- Docker must be installed and running locally.
- The selected repository is mounted into the container; use `repository_read_only=True` for
  read-only checks when possible.
- This is a safer execution boundary, not a perfect security boundary for malicious code.
- Network is disabled by default, so commands that need downloads should fail unless explicitly
  configured otherwise.

## Git And GitHub Workflow (Phase 13)

Phase 13 adds local Git workflow helpers for repository automation:

- clone a public repository or local test mirror
- create a branch
- inspect diffs
- commit selected or all changes
- generate a PR title/body
- optionally push a branch or create a GitHub PR only after explicit approval

GitHub PR creation uses the GitHub CLI (`gh`) and a configured token. Tokens are read from
environment variables and are never returned in tool results.

Optional setup:

```bash
brew install gh
export GITHUB_TOKEN="ghp_your_token_here"
```

Safety rules:

- Push and PR creation require an explicit `approved=True` argument in code.
- GitHub tokens are not passed to agents or included in generated summaries.
- GitHub command errors redact configured token values before surfacing output.
- Branch names, refs, paths, and clone URLs are validated before commands run.

## Ollama Setup (Phase 2)

DevTeam AI uses Ollama as the default local/free LLM provider.

Install Ollama from [ollama.com](https://ollama.com), then start the local server:

```bash
ollama serve
```

Pull the default model:

```bash
ollama pull llama3.1
```

Optional environment variables:

```bash
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
export OLLAMA_MODEL="llama3.1"
export OLLAMA_TIMEOUT_SECONDS="30"
```

Internal provider smoke test:

```bash
cd backend
python -c "from app.llm import generate_text; print(generate_text('Reply with ok.').text)"
```

Tests use a mock provider and do not require Ollama to be installed or running.

## Quality Checks

From the `backend/` directory:

```bash
cd backend
pytest
ruff check .
ruff format --check .
mypy app
bandit -r app

# Optional if Semgrep Community Edition is installed:
semgrep scan --config auto
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

Phase 2 LLM provider abstraction is implemented:

- Provider-neutral request and response models
- Abstract `LLMProvider` interface
- Ollama client using local `/api/generate`
- Environment-based Ollama configuration
- Clear errors for connection failure, missing model, timeout, and malformed responses
- Mock-provider tests that do not require Ollama

Phase 3 Planner and Architect agents are implemented:

- Prompt templates for structured task planning and architecture design
- Planner Agent that validates LLM output into `TaskList`
- Architect Agent that validates LLM output into `ArchitecturePlan`
- Shared JSON parsing and schema-validation error handling
- Fake-provider tests that do not require a real LLM

Phase 4 repository inspection and file tools are implemented:

- Safe file listing, reading, and writing inside a selected repository
- Path traversal prevention for repository file operations
- Code search with line-level matches
- Repository tree summaries that ignore generated and dependency directories
- Tests for file safety and small Python repo summarization

Phase 5 Coder Agent and patch tools are implemented:

- Coder Agent that turns implementation context into a validated unified diff
- Safe unified-diff parser and applicator for repository files
- `get_diff` helper for displaying final git diffs
- Tests for patch parsing, application, traversal rejection, and Coder Agent output validation

Phase 6 Tester Agent and pytest runner are implemented:

- Tester Agent that generates validated pytest test patches
- Pytest runner with timeout support
- Pytest result parser for pass/fail/skip counts and failed test names
- FastAPI demo app under `examples/fastapi-demo-app`
- Tests proving generated tests can be applied to the demo app and run successfully

Phase 7 static-analysis quality gates are implemented:

- Ruff lint runner and Ruff format-check runner
- mypy type-check runner
- Bandit security scan runner
- Optional Semgrep Community Edition runner when installed
- Combined quality gate runner for pytest plus static analysis
- Graceful skipped-tool reporting when a scanner is not installed

Phase 8 Reviewer Agent and repair loop are implemented:

- Reviewer Agent that returns structured approval or repair feedback
- Review issues with severity, source, optional file/line, and suggested fix
- Manual repair loop for approval, rejection, test repair, code repair, and max-iteration stop
- Tests with mock reviewer, repair agents, and quality gate results

Phase 9 LangGraph workflow orchestration is implemented:

- LangGraph `StateGraph` workflow with nodes for repo context, planner, architect, coder, tester, quality gates, reviewer, and finalize
- Conditional routing for approval, coder repair, tester repair, rerun checks, and max-iteration finalization
- `run_devteam_workflow` service function for local repo feature requests
- Tests with mocked node functions covering expected sequence and routing behavior

Phase 10 FastAPI run-management endpoints are implemented:

- `POST /runs` starts a synchronous local workflow run
- `GET /runs/{run_id}` returns persisted run state
- `GET /runs/{run_id}/diff` returns the final captured diff
- `GET /runs/{run_id}/logs` returns derived agent and quality-gate logs
- SQLite run history with dependency-injected tests that do not require Ollama

Phase 11 Streamlit dashboard is implemented:

- UI inputs for local repo path, feature request, max iterations, backend URL, and existing run id
- Run status, final summary, and agent timeline
- Planner task list and Architect design sections
- Diff viewer, pytest results, static-analysis results, and Reviewer feedback
- Clear local demo instructions for running backend and UI together

Phase 12 Docker sandbox execution is implemented:

- Docker sandbox runner for allowlisted test and static-analysis commands
- Resource limits for timeout, memory, CPU, PID count, and temporary writable cache space
- Network disabled by default with an explicit configuration option
- Safe repository mount construction and command validation
- Sandbox Dockerfile with pytest, Ruff, mypy, Bandit, and Semgrep Community Edition
- Tests for allowed commands, blocked dangerous commands, Docker command construction, and runner results

Phase 13 Git and GitHub integration is implemented:

- Git helpers for public clone, branch creation, diff inspection, and commits
- PR title/body generation from feature summaries and changed files
- Optional branch push and GitHub PR creation gated by explicit approval flags
- Token-safe GitHub CLI integration with redacted error output
- Tests using temporary Git repositories and mocked GitHub CLI calls
