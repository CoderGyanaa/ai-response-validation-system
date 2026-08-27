"""
Common interface every judge agent implements, so the orchestrator can
loop over agents without knowing their internals.
"""
from abc import ABC, abstractmethod
from app.models.schemas import EvaluationRequest, JudgeResult


class BaseJudgeAgent(ABC):
    name: str = "base"

    @abstractmethod
    def evaluate(self, request: EvaluationRequest, evidence: list[str]) -> JudgeResult:
        """Run this agent's judgment and return a structured result."""
        raise NotImplementedError
