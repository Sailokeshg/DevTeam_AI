"""Planner Agent implementation."""

from pathlib import Path

from app.agents.parsing import parse_json_model
from app.llm.base import LLMGenerationRequest, LLMProvider
from app.schemas.task import TaskList

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "planner.md"


class PlannerAgent:
    """Converts a feature request into a validated task list."""

    def __init__(self, llm_provider: LLMProvider, prompt_path: Path = PROMPT_PATH):
        self.llm_provider = llm_provider
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

    def plan(self, user_request: str, repository_summary: str | None = None) -> TaskList:
        """Generate and validate a structured task list."""
        prompt = self._build_prompt(
            user_request=user_request, repository_summary=repository_summary
        )
        response = self.llm_provider.generate(
            LLMGenerationRequest(prompt=prompt, system_prompt=self.system_prompt, temperature=0.1)
        )
        return parse_json_model(response.text, TaskList, "Planner Agent output")

    def _build_prompt(self, user_request: str, repository_summary: str | None) -> str:
        repo_context = repository_summary or "No repository summary is available yet."
        return (
            "Create a task list for this feature request.\n\n"
            f"Feature request:\n{user_request}\n\n"
            f"Repository summary:\n{repo_context}\n\n"
            "Return only JSON that matches the required schema."
        )
