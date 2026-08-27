import logging

from app.agents.base import BaseJudgeAgent
from app.agents.prompt_utils import extract_json, format_evidence
from app.models.schemas import EvaluationRequest, JudgeResult
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are an evaluation judge. Score the ACCURACY of the AI response — whether its factual claims are correct, checked against the reference evidence and reference answer (if provided).

Question: {question}

AI Response: {ai_response}

Reference Answer: {reference_answer}

Retrieved Evidence:
{evidence}

Score from 0.0 (factually wrong) to 1.0 (fully accurate and supported).
If there is no evidence or reference to check against, judge based on your own knowledge but note that in the reason.

Respond with ONLY a JSON object, no other text:
{{"score": <float 0.0-1.0>, "reason": "<one sentence explaining the score>"}}
"""


class AccuracyJudgeAgent(BaseJudgeAgent):
    """Checks whether factual claims in the response are correct against evidence/reference."""
    name = "accuracy"

    def __init__(self) -> None:
        self.llm = LLMClient()

    def evaluate(self, request: EvaluationRequest, evidence: list[str]) -> JudgeResult:
        prompt = PROMPT_TEMPLATE.format(
            question=request.question,
            ai_response=request.ai_response,
            reference_answer=request.reference_answer or "(not provided)",
            evidence=format_evidence(evidence),
        )
        try:
            raw = self.llm.complete(prompt)
            parsed = extract_json(raw)
            return JudgeResult(
                agent_name=self.name,
                score=float(parsed["score"]),
                reason=parsed.get("reason", ""),
                evidence=evidence[:3],
            )
        except Exception:
            logger.exception("Accuracy agent failed to score")
            return JudgeResult(
                agent_name=self.name,
                score=0.0,
                reason="Evaluation failed due to an internal error (LLM call or parsing failed).",
                evidence=[],
            )
