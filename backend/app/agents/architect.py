"""Architect Agent implementation."""

from pathlib import Path

from app.agents.parsing import parse_json_model
from app.llm.base import LLMGenerationRequest, LLMProvider
from app.schemas.agent_state import ArchitecturePlan
from app.schemas.task import TaskList

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "architect.md"


class ArchitectAgent:
    """Produces an implementation design from repo context and planned tasks."""

    def __init__(self, llm_provider: LLMProvider, prompt_path: Path = PROMPT_PATH):
        self.llm_provider = llm_provider
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

    def design(
        self,
        *,
        user_request: str,
        repository_summary: str,
        task_list: TaskList,
    ) -> ArchitecturePlan:
        """Generate and validate a structured architecture plan."""
        prompt = self._build_prompt(
            user_request=user_request,
            repository_summary=repository_summary,
            task_list=task_list,
        )
        response = self.llm_provider.generate(
            LLMGenerationRequest(prompt=prompt, system_prompt=self.system_prompt, temperature=0.1)
        )
        return parse_json_model(response.text, ArchitecturePlan, "Architect Agent output")

    def _build_prompt(
        self,
        *,
        user_request: str,
        repository_summary: str,
        task_list: TaskList,
    ) -> str:
        return (
            "Create an architecture plan for this implementation.\n\n"
            f"Feature request:\n{user_request}\n\n"
            f"Repository summary:\n{repository_summary}\n\n"
            f"Task list JSON:\n{task_list.model_dump_json(indent=2)}\n\n"
            "Return only JSON that matches the required schema."
        )
