import logging

from app.agents.base import BaseJudgeAgent
from app.agents.prompt_utils import extract_json, format_evidence
from app.models.schemas import EvaluationRequest, HallucinationResult, FlaggedClaim
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

VALID_STATUSES = {"none", "partial", "full"}

PROMPT_TEMPLATE = """You are a Hallucination Detection Judge. Break the AI response into its individual factual claims, then cross-reference EACH claim against the retrieved evidence.

Question: {question}

AI Response: {ai_response}

Retrieved Evidence:
{evidence}

Rules:
- FIRST, check whether the response is actually attempting to answer the question. If the response does not attempt to answer the question at all (it is off-topic, or discusses a related subject without addressing what was asked), do NOT flag its claims as unsupported just because they are absent from the retrieved evidence. Set hallucination_status to "none" and explain in the reason that the response doesn't attempt to answer the question, so hallucination doesn't apply. Only evaluate claims for hallucination when the response IS attempting to answer the question asked.
- If there is no evidence at all, you cannot verify any claim — set hallucination_status to "none" and say in the reason that verification wasn't possible, rather than guessing.
- For every claim in the response that IS an attempt to answer the question and is NOT supported by the evidence (unsupported, fabricated, or directly contradicted), add an entry to "claims": one object per flagged claim.
- Each flagged claim needs: the exact claim text, whether it is supported (always false for flagged claims), the specific evidence snippet that contradicts or fails to support it (or empty if no evidence exists), and a one-sentence reason.
- hallucination_status: "none" if all claims are supported, unverifiable, or the response doesn't attempt to answer the question; "partial" if some answering claims are unsupported; "full" if the entire answer is fabricated/unsupported or directly contradicts the evidence.
- score = fraction of the response that IS supported by evidence (1.0 = fully supported, 0.0 = fully unsupported). A response that doesn't attempt to answer the question scores 1.0 here (nothing to contradict), since that failure belongs to the Relevance judge, not this one.

Example: Question "What is the capital of France?" / Response "France is known for its cuisine." → this doesn't attempt to answer, so hallucination_status = "none", score = 1.0.
Example: Question "What is the capital of France?" / Response "The capital of France is Berlin." → this DOES attempt to answer and directly contradicts evidence that the capital is Paris, so hallucination_status = "full".

Respond with ONLY a JSON object, no other text:
{{
  "score": <float 0.0-1.0>,
  "hallucination_status": "<none|partial|full>",
  "claims": [
    {{"claim": "<exact or near-exact text from the response>", "supported": false, "evidence": ["<contradicting evidence snippet, or omit>"], "reason": "<why this is unsupported>"}}
  ],
  "reason": "<one sentence overall verdict>"
}}
"""


class HallucinationDetectionAgent(BaseJudgeAgent):
    """Flags specific unsupported claims in the response, cross-referenced against retrieved evidence."""
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

            status = parsed.get("hallucination_status", "")
            if status not in VALID_STATUSES:
                logger.warning("Hallucination agent returned unexpected status: %r", status)
                status = "partial" if parsed.get("claims") else "none"

            raw_claims = parsed.get("claims", [])
            claim_evidence = [
                FlaggedClaim(
                    claim=c.get("claim", ""),
                    supported=bool(c.get("supported", False)),
                    evidence=c.get("evidence", []) or [],
                    reason=c.get("reason", ""),
                )
                for c in raw_claims
                if isinstance(c, dict) and c.get("claim")
            ]
            unsupported_claims = [c.claim for c in claim_evidence]

            return HallucinationResult(
                agent_name=self.name,
                score=float(parsed["score"]),
                category=status,
                reason=parsed.get("reason", ""),
                evidence=evidence[:3],
                hallucination_detected=len(claim_evidence) > 0,
                hallucination_status=status,
                unsupported_claims=unsupported_claims,
                claim_evidence=claim_evidence,
            )
        except Exception:
            logger.exception("Hallucination agent failed to score")
            return HallucinationResult(
                agent_name=self.name,
                score=0.0,
                category="none",
                reason="Evaluation failed due to an internal error (LLM call or parsing failed).",
                evidence=[],
                hallucination_detected=False,
                hallucination_status="none",
                unsupported_claims=[],
                claim_evidence=[],
            )
