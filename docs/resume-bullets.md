# DevTeam AI Resume Bullets

## Short Version

- Built DevTeam AI, a local-first multi-agent software engineering system using FastAPI, LangGraph, Ollama, Streamlit, Docker, and Python.
- Designed typed Planner, Architect, Coder, Tester, and Reviewer agents that transform feature requests into tasks, design plans, patches, tests, quality results, and review decisions.
- Implemented a LangGraph repair loop with pytest, Ruff, mypy, Bandit, optional Semgrep, and max-iteration stopping logic.
- Added path-safe repository tools, patch-based code application, Docker sandbox execution, SQLite run history, and token-safe Git/GitHub helpers.

## Detailed Bullets

- Architected a multi-agent development workflow that coordinates planning, architecture, coding, testing, static analysis, review, and iterative repair through a shared typed state model.
- Implemented local/free LLM provider abstraction with Ollama by default, plus fake providers for deterministic unit tests and CI-friendly validation.
- Built safety-focused repository tooling with path traversal prevention, unified-diff patch application, command allowlisting, Docker resource limits, and explicit approval gates for push/PR operations.
- Created FastAPI run-management endpoints and a Streamlit dashboard that displays agent timeline, task list, architecture plan, code diff, pytest output, static-analysis findings, reviewer feedback, and final status.
- Developed comprehensive backend tests covering schemas, agents, parsers, file safety, patch application, quality gates, repair routing, LangGraph orchestration, API storage, Docker validation, and Git workflows.

## Project Pitch

DevTeam AI demonstrates how AI coding assistants can be structured like an engineering team instead of a single prompt. The system decomposes a request, validates every agent output, applies focused patches, runs quality gates, reviews the result, and iterates with traceable state until approval or failure.

## Technologies

- Python 3.11+
- FastAPI
- LangGraph
- Ollama
- Pydantic
- Streamlit
- Docker
- pytest
- Ruff
- mypy
- Bandit
- Semgrep Community Edition
- Git CLI and GitHub CLI
- SQLite
