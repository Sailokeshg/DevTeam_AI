"""Coder Agent implementation."""

import re
import textwrap
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.agents.parsing import AgentOutputError
from app.llm.base import LLMGenerationRequest, LLMProvider
from app.schemas.agent_state import ArchitecturePlan
from app.schemas.task import NonEmptyStr, TaskList
from app.tools.patch_tools import PatchParseError, validate_unified_diff

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "coder.md"


class RelevantFile(BaseModel):
    """A repository file included as implementation context for the Coder Agent."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    path: NonEmptyStr
    content: str


class CoderAgent:
    """Generates focused unified diffs for planned code changes."""

    def __init__(self, llm_provider: LLMProvider, prompt_path: Path = PROMPT_PATH):
        self.llm_provider = llm_provider
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

    def generate_patch(
        self,
        *,
        user_request: str,
        task_list: TaskList,
        architecture_plan: ArchitecturePlan,
        relevant_files: list[RelevantFile],
    ) -> str:
        """Generate and validate a unified diff without applying it."""
        prompt = self._build_prompt(
            user_request=user_request,
            task_list=task_list,
            architecture_plan=architecture_plan,
            relevant_files=relevant_files,
        )
        response = self.llm_provider.generate(
            LLMGenerationRequest(prompt=prompt, system_prompt=self.system_prompt, temperature=0.1)
        )
        patch = extract_unified_diff(response.text)

        try:
            validate_unified_diff(patch)
        except PatchParseError as exc:
            message = f"Coder Agent output was not a valid unified diff: {exc}"
            raise AgentOutputError(message) from exc

        return patch

    def _build_prompt(
        self,
        *,
        user_request: str,
        task_list: TaskList,
        architecture_plan: ArchitecturePlan,
        relevant_files: list[RelevantFile],
    ) -> str:
        rendered_files = "\n\n".join(_render_file_context(file) for file in relevant_files)
        if not rendered_files:
            rendered_files = "No relevant file contents were provided."

        return (
            "Generate a minimal unified diff for the requested implementation.\n\n"
            f"Feature request:\n{user_request}\n\n"
            f"Task list JSON:\n{task_list.model_dump_json(indent=2)}\n\n"
            f"Architecture plan JSON:\n{architecture_plan.model_dump_json(indent=2)}\n\n"
            f"Relevant files:\n{rendered_files}\n\n"
            "Return only a unified diff."
        )


def extract_unified_diff(output: str) -> str:
    """Extract a unified diff from raw model output or fenced diff blocks."""
    text = output.strip()
    fenced_match = re.search(r"```(?:diff|patch)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        text = _normalize_diff_block(fenced_match.group(1))

    diff_start = _find_diff_start(text)
    if diff_start == -1:
        raise AgentOutputError("Coder Agent response did not contain a unified diff")

    return text[diff_start:].strip() + "\n"


def _find_diff_start(text: str) -> int:
    for marker in ("diff --git ", "--- "):
        index = text.find(marker)
        if index != -1:
            return index
    return -1


def _normalize_diff_block(block: str) -> str:
    text = textwrap.dedent(block).strip()
    lines = text.splitlines()
    header_indents = [
        len(line) - len(line.lstrip(" "))
        for line in lines[1:]
        if line.lstrip(" ").startswith(("--- ", "+++ ", "@@ ", "diff --git "))
    ]
    removable_indent = min((indent for indent in header_indents if indent > 0), default=0)

    if removable_indent == 0:
        return text

    indentation = " " * removable_indent
    normalized_lines = [
        line[removable_indent:] if line.startswith(indentation) else line for line in lines
    ]
    return "\n".join(normalized_lines)


def _render_file_context(file: RelevantFile) -> str:
    return f"File: {file.path}\n```text\n{file.content}\n```"
