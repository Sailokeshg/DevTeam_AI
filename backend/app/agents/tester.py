"""Tester Agent implementation."""

from pathlib import Path

from app.agents.coder import RelevantFile, extract_unified_diff
from app.agents.parsing import AgentOutputError
from app.llm.base import LLMGenerationRequest, LLMProvider
from app.schemas.agent_state import ArchitecturePlan
from app.schemas.task import TaskList
from app.tools.patch_tools import PatchParseError, validate_unified_diff

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "tester.md"


class TesterAgent:
    """Generates pytest-focused unified diffs for test coverage."""

    def __init__(self, llm_provider: LLMProvider, prompt_path: Path = PROMPT_PATH):
        self.llm_provider = llm_provider
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

    def generate_test_patch(
        self,
        *,
        user_request: str,
        task_list: TaskList,
        architecture_plan: ArchitecturePlan,
        relevant_files: list[RelevantFile],
        implementation_diff: str | None = None,
    ) -> str:
        """Generate and validate a unified diff containing pytest tests."""
        prompt = self._build_prompt(
            user_request=user_request,
            task_list=task_list,
            architecture_plan=architecture_plan,
            relevant_files=relevant_files,
            implementation_diff=implementation_diff,
        )
        response = self.llm_provider.generate(
            LLMGenerationRequest(prompt=prompt, system_prompt=self.system_prompt, temperature=0.1)
        )
        patch = extract_unified_diff(response.text)

        try:
            validate_unified_diff(patch)
        except PatchParseError as exc:
            message = f"Tester Agent output was not a valid unified diff: {exc}"
            raise AgentOutputError(message) from exc

        return patch

    def _build_prompt(
        self,
        *,
        user_request: str,
        task_list: TaskList,
        architecture_plan: ArchitecturePlan,
        relevant_files: list[RelevantFile],
        implementation_diff: str | None,
    ) -> str:
        rendered_files = "\n\n".join(_render_file_context(file) for file in relevant_files)
        if not rendered_files:
            rendered_files = "No relevant file contents were provided."

        diff_context = implementation_diff or "No implementation diff was provided."
        return (
            "Generate pytest tests as a minimal unified diff.\n\n"
            f"Feature request:\n{user_request}\n\n"
            f"Task list JSON:\n{task_list.model_dump_json(indent=2)}\n\n"
            f"Architecture plan JSON:\n{architecture_plan.model_dump_json(indent=2)}\n\n"
            f"Implementation diff:\n{diff_context}\n\n"
            f"Relevant files:\n{rendered_files}\n\n"
            "Return only a unified diff that creates or updates pytest test files."
        )


def _render_file_context(file: RelevantFile) -> str:
    return f"File: {file.path}\n```text\n{file.content}\n```"
