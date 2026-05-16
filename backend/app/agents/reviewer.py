"""Reviewer Agent implementation."""

from pathlib import Path

from app.agents.parsing import parse_json_model
from app.llm.base import LLMGenerationRequest, LLMProvider
from app.schemas.agent_state import AgentState, ArchitecturePlan, StaticAnalysisResult, TestResult
from app.schemas.review import ReviewResult

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "reviewer.md"


class ReviewerAgent:
    """Reviews diffs and quality-gate output into a structured decision."""

    def __init__(self, llm_provider: LLMProvider, prompt_path: Path = PROMPT_PATH):
        self.llm_provider = llm_provider
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

    def review(
        self,
        *,
        user_request: str,
        architecture_plan: ArchitecturePlan,
        code_diff: str,
        test_results: list[TestResult],
        static_analysis_results: list[StaticAnalysisResult],
    ) -> ReviewResult:
        """Generate and validate a structured review result."""
        prompt = self._build_prompt(
            user_request=user_request,
            architecture_plan=architecture_plan,
            code_diff=code_diff,
            test_results=test_results,
            static_analysis_results=static_analysis_results,
        )
        response = self.llm_provider.generate(
            LLMGenerationRequest(prompt=prompt, system_prompt=self.system_prompt, temperature=0.1)
        )
        return parse_json_model(response.text, ReviewResult, "Reviewer Agent output")

    def review_state(self, state: AgentState) -> ReviewResult:
        """Review the current workflow state."""
        if state.architecture_plan is None:
            raise ValueError("AgentState must include architecture_plan before review")

        return self.review(
            user_request=state.user_request,
            architecture_plan=state.architecture_plan,
            code_diff=state.diff or state.patch or "",
            test_results=state.test_results,
            static_analysis_results=[
                *state.lint_results,
                *state.type_check_results,
                *state.security_results,
            ],
        )

    def _build_prompt(
        self,
        *,
        user_request: str,
        architecture_plan: ArchitecturePlan,
        code_diff: str,
        test_results: list[TestResult],
        static_analysis_results: list[StaticAnalysisResult],
    ) -> str:
        return (
            "Review this implementation and quality-gate output.\n\n"
            f"Feature request:\n{user_request}\n\n"
            f"Architecture plan JSON:\n{architecture_plan.model_dump_json(indent=2)}\n\n"
            f"Code diff:\n{code_diff or 'No diff was provided.'}\n\n"
            "Test results JSON:\n"
            f"{_dump_models(test_results)}\n\n"
            "Static-analysis results JSON:\n"
            f"{_dump_models(static_analysis_results)}\n\n"
            "Return only JSON that matches the required review schema."
        )


def _dump_models(models: list[TestResult] | list[StaticAnalysisResult]) -> str:
    return "[" + ", ".join(model.model_dump_json() for model in models) + "]"
