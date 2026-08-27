import logging

from app.agents.base import BaseJudgeAgent
from app.agents.prompt_utils import extract_json, format_evidence
from app.models.schemas import EvaluationRequest, HallucinationResult
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are a hallucination detection judge. Compare the AI response's claims against the retrieved evidence. Identify any claims made in the response that are NOT supported by the evidence — these are potential hallucinations.

Question: {question}

AI Response: {ai_response}

Retrieved Evidence:
{evidence}

Rules:
- If there is no evidence at all, you cannot verify claims — set hallucination_detected to false and note in the reason that verification wasn't possible, rather than guessing.
- List each unsupported claim as a short quote or paraphrase from the response.
- score = fraction of the response that IS supported by evidence (1.0 = fully supported, 0.0 = fully unsupported).

Respond with ONLY a JSON object, no other text:
{{"score": <float 0.0-1.0>, "hallucination_detected": <true/false>, "unsupported_claims": ["<claim1>", "..."], "reason": "<one sentence explaining the verdict>"}}
"""


class HallucinationDetectionAgent(BaseJudgeAgent):
    """Flags claims in the response that are not supported by retrieved evidence."""
    name = "hallucination"

    def __init__(self) -> None:
        self.llm = LLMClient()

    def evaluate(self, request: EvaluationRequest, evidence: list[str]) -> HallucinationResult:
        prompt = PROMPT_TEMPLATE.format(
            question=request.question,
            ai_response=request.ai_response,
            evidence=format_evidence(evidence),
        )
        try:
            raw = self.llm.complete(prompt)
            parsed = extract_json(raw)
            return HallucinationResult(
                agent_name=self.name,
                score=float(parsed["score"]),
                reason=parsed.get("reason", ""),
                evidence=evidence[:3],
                hallucination_detected=bool(parsed.get("hallucination_detected", False)),
                unsupported_claims=parsed.get("unsupported_claims", []),
            )
        except Exception:
            logger.exception("Hallucination agent failed to score")
            return HallucinationResult(
                agent_name=self.name,
                score=0.0,
                reason="Evaluation failed due to an internal error (LLM call or parsing failed).",
                evidence=[],
                hallucination_detected=False,
                unsupported_claims=[],
            )
