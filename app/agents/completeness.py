import logging

from app.agents.base import BaseJudgeAgent
from app.agents.prompt_utils import extract_json, format_evidence
from app.models.schemas import EvaluationRequest, CompletenessResult
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are a Completeness Judge. First identify the individual requirements or sub-questions contained in the question, then determine which ones the AI response addresses, partially addresses, or omits entirely.

Question: {question}

AI Response: {ai_response}

Reference Answer: {reference_answer}

Retrieved Evidence:
{evidence}

If a reference answer is provided, use it to identify what information should be covered. Otherwise use the retrieved evidence. If neither is available, judge based on what the question itself clearly asks for.

Use this scoring scale:
- 1.0 = all identified requirements/sub-questions are addressed.
- 0.5 to 0.7 = some requirements are addressed, at least one is missing or under-covered.
- 0.0 to 0.3 = most requirements are missing, or only a minor part of the question was answered.

Respond with ONLY a JSON object, no other text:
{{
  "score": <float 0.0-1.0>,
  "addressed_aspects": ["<requirement or sub-question the response covers>"],
  "missing_aspects": ["<requirement or sub-question the response omits or under-covers>"],
  "reason": "<one sentence explaining the score>"
}}
"""


class CompletenessJudgeAgent(BaseJudgeAgent):
    """Checks whether the response covers every requirement/sub-question in the prompt, listing specific omissions."""
    name = "completeness"

    def __init__(self) -> None:
        self.llm = LLMClient()

    def evaluate(self, request: EvaluationRequest, evidence: list[str]) -> CompletenessResult:
        prompt = PROMPT_TEMPLATE.format(
            question=request.question,
            ai_response=request.ai_response,
            reference_answer=request.reference_answer or "(not provided)",
            evidence=format_evidence(evidence),
        )
        try:
            raw = self.llm.complete(prompt)
            parsed = extract_json(raw)
            missing = parsed.get("missing_aspects", []) or []
            category = "complete" if not missing else ("mostly_complete" if float(parsed["score"]) >= 0.5 else "incomplete")
            return CompletenessResult(
                agent_name=self.name,
                score=float(parsed["score"]),
                category=category,
                reason=parsed.get("reason", ""),
                evidence=[],
                addressed_aspects=parsed.get("addressed_aspects", []) or [],
                missing_aspects=missing,
            )
        except Exception:
            logger.exception("Completeness agent failed to score")
            return CompletenessResult(
                agent_name=self.name,
                score=0.0,
                category="",
                reason="Evaluation failed due to an internal error (LLM call or parsing failed).",
                evidence=[],
                addressed_aspects=[],
                missing_aspects=[],
            )
