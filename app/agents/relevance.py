import logging

from app.agents.base import BaseJudgeAgent
from app.agents.prompt_utils import extract_json, format_evidence
from app.models.schemas import EvaluationRequest, JudgeResult
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are an evaluation judge. Score how RELEVANT the AI response is to the question — i.e. does it actually address what was asked, regardless of whether it's factually correct.

Question: {question}

AI Response: {ai_response}

Score from 0.0 (completely off-topic) to 1.0 (fully addresses the question).

Respond with ONLY a JSON object, no other text:
{{"score": <float 0.0-1.0>, "reason": "<one sentence explaining the score>"}}
"""


class RelevanceJudgeAgent(BaseJudgeAgent):
    """Checks whether the AI response actually addresses the question asked."""
    name = "relevance"

    def __init__(self) -> None:
        self.llm = LLMClient()

    def evaluate(self, request: EvaluationRequest, evidence: list[str]) -> JudgeResult:
        prompt = PROMPT_TEMPLATE.format(
            question=request.question,
            ai_response=request.ai_response,
        )
        try:
            raw = self.llm.complete(prompt)
            parsed = extract_json(raw)
            return JudgeResult(
                agent_name=self.name,
                score=float(parsed["score"]),
                reason=parsed.get("reason", ""),
                evidence=[],
            )
        except Exception:
            logger.exception("Relevance agent failed to score")
            return JudgeResult(
                agent_name=self.name,
                score=0.0,
                reason="Evaluation failed due to an internal error (LLM call or parsing failed).",
                evidence=[],
            )
