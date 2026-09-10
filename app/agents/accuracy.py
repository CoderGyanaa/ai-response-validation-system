import logging

from app.agents.base import BaseJudgeAgent
from app.agents.prompt_utils import extract_json, format_evidence
from app.models.schemas import EvaluationRequest, JudgeResult
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

# Defined scoring scale (M2.2): explicit bands + categories for factual correctness.
VALID_CATEGORIES = {"correct", "partially_correct", "incorrect", "contradictory"}

PROMPT_TEMPLATE = """You are an Accuracy Judge. Evaluate the factual correctness of the AI response.

Question: {question}

AI Response: {ai_response}

Reference Answer: {reference_answer}

Retrieved Evidence:
{evidence}

Compare the response against the reference answer if provided; otherwise use the retrieved evidence. If neither is available, judge based on your own knowledge and say so in the reason.

Use this scoring scale:
- 1.0 = "correct" — all factual claims match the reference/evidence.
- 0.5 to 0.7 = "partially_correct" — the response contains multiple substantive claims and at least one important claim is correct while another is incorrect or unverifiable. Do NOT classify the whole response as "incorrect" just because one claim is seriously wrong — if any substantive part is right, it is partially_correct.
- 0.1 to 0.3 = "incorrect" — the response makes essentially one claim (or all claims), and it is factually wrong.
- 0.0 = "contradictory" — the response directly and entirely contradicts the reference/evidence, with no correct claim present.

Example: "The capital of France is Paris, and it has a population of about 50 million." — the capital claim (Paris) is correct, the population claim is wrong. This is "partially_correct", not "incorrect", because one substantive claim is right.

Respond with ONLY a JSON object, no other text:
{{"score": <float 0.0-1.0>, "category": "<correct|partially_correct|incorrect|contradictory>", "reason": "<one sentence explaining the score>"}}
"""


class AccuracyJudgeAgent(BaseJudgeAgent):
    """Checks whether factual claims in the response are correct against evidence/reference, per a defined scoring scale."""
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
            category = parsed.get("category", "")
            if category not in VALID_CATEGORIES:
                logger.warning("Accuracy agent returned unexpected category: %r", category)
                category = ""
            return JudgeResult(
                agent_name=self.name,
                score=float(parsed["score"]),
                category=category,
                reason=parsed.get("reason", ""),
                evidence=evidence[:3],
            )
        except Exception:
            logger.exception("Accuracy agent failed to score")
            return JudgeResult(
                agent_name=self.name,
                score=0.0,
                category="",
                reason="Evaluation failed due to an internal error (LLM call or parsing failed).",
                evidence=[],
            )
