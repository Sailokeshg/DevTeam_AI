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

Phase 4 repository inspection and file tools are implemented:

- Safe path resolution that prevents access outside the selected repository
- File listing, reading, writing, and code search helpers
- Repository tree summaries with basic file-extension statistics
- Common generated and dependency directories ignored during inspection
- Tests for path safety, ignored folders, search, and summarization
