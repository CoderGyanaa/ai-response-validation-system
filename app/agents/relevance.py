import logging

from app.agents.base import BaseJudgeAgent
from app.agents.prompt_utils import extract_json, format_evidence
from app.models.schemas import EvaluationRequest, JudgeResult
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

# Defined scoring scale (M2.1): each band has explicit criteria so the LLM
# judge applies a consistent rubric instead of picking an arbitrary float.
VALID_CATEGORIES = {"fully_relevant", "partially_relevant", "unrelated", "off_topic"}

PROMPT_TEMPLATE = """You are a Relevance Judge. Score whether the AI response directly and appropriately addresses the question asked — regardless of whether the response is factually correct.

Question: {question}

AI Response: {ai_response}

Use this scoring scale:
- 1.0 = "fully_relevant" — the response directly and completely addresses what was asked.
- 0.5 to 0.7 = "partially_relevant" — the response addresses part of the question, or answers a related but slightly different question.
- 0.1 to 0.3 = "unrelated" — the response is about the same general subject/topic as the question, but does not answer the specific question asked.
  Example: Question "What is the capital of France?" / Response "France is known for its cuisine, especially cheese and wine." → unrelated (same topic — France — but doesn't answer what the capital is).
- 0.0 = "off_topic" — the response has no meaningful connection to the question's subject at all.
  Example: Question "What is the capital of France?" / Response "I enjoy playing chess on weekends." → off_topic (no connection to France or capitals).

Respond with ONLY a JSON object, no other text:
{{"score": <float 0.0-1.0>, "category": "<fully_relevant|partially_relevant|unrelated|off_topic>", "reason": "<one sentence explaining the score>"}}
"""


class RelevanceJudgeAgent(BaseJudgeAgent):
    """Checks whether the AI response actually addresses the question asked, per a defined scoring scale."""
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
            category = parsed.get("category", "")
            if category not in VALID_CATEGORIES:
                logger.warning("Relevance agent returned unexpected category: %r", category)
                category = ""
            return JudgeResult(
                agent_name=self.name,
                score=float(parsed["score"]),
                category=category,
                reason=parsed.get("reason", ""),
                evidence=[],
            )
        except Exception:
            logger.exception("Relevance agent failed to score")
            return JudgeResult(
                agent_name=self.name,
                score=0.0,
                category="",
                reason="Evaluation failed due to an internal error (LLM call or parsing failed).",
                evidence=[],
            )
