import logging

from app.agents.base import BaseJudgeAgent
from app.agents.prompt_utils import extract_json, format_evidence
from app.models.schemas import EvaluationRequest, JudgeResult
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are an evaluation judge. Score the COMPLETENESS of the AI response — does it fully answer all parts of the question, without leaving out important information (compared to the reference answer/evidence, if available)?

Question: {question}

AI Response: {ai_response}

Reference Answer: {reference_answer}

Retrieved Evidence:
{evidence}

Score from 0.0 (major parts missing) to 1.0 (fully complete).

Respond with ONLY a JSON object, no other text:
{{"score": <float 0.0-1.0>, "reason": "<one sentence explaining the score>"}}
"""


class CompletenessJudgeAgent(BaseJudgeAgent):
    """Checks whether the response covers all parts of the question / reference answer."""
    name = "completeness"

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
                evidence=[],
            )
        except Exception:
            logger.exception("Completeness agent failed to score")
            return JudgeResult(
                agent_name=self.name,
                score=0.0,
                reason="Evaluation failed due to an internal error (LLM call or parsing failed).",
                evidence=[],
            )
