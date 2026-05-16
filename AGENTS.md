# AGENTS.md

## Purpose

This file defines contributor rules for DevTeam AI so the codebase stays consistent, testable, and safe.

## Coding Conventions

- Use Python 3.11+
- Add type annotations where practical
- Keep modules focused and small
- Prefer explicit data models over unstructured dictionaries
- Keep comments short and only for non-obvious logic
- Do not hardcode secrets or tokens

## Testing and Checks

Run these commands from `backend/`:

```bash
cd backend
pytest
ruff check .
ruff format --check .
mypy app
```

## Project Rules

- Build phase-by-phase; do not jump ahead without explicit request
- Keep changes minimal and focused per task
- Do not run generated code unrestricted on the host machine
- Prefer Docker/sandbox execution for untrusted operations
- Update documentation when behavior or setup changes
