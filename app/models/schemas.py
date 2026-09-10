"""
Typed data models (Pydantic) shared across the API, evaluation service, and agents.
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class EvaluationRequest(BaseModel):
    question: str = Field(..., min_length=1, description="The question posed to the AI")
    ai_response: str = Field(..., min_length=1, description="The AI-generated response to evaluate")
    reference_answer: Optional[str] = Field(None, description="Optional ground-truth answer")
    source_document: Optional[str] = Field(None, description="Optional source/reference material")


class JudgeResult(BaseModel):
    agent_name: str
    score: float = Field(..., ge=0, le=1)
    category: str = Field("", description="Discrete label for the score band, e.g. 'fully_relevant', 'incorrect'")
    reason: str
    evidence: List[str] = []


class FlaggedClaim(BaseModel):
    claim: str
    supported: bool
    evidence: List[str] = []
    reason: str = ""


class HallucinationResult(JudgeResult):
    hallucination_detected: bool
    hallucination_status: str = Field("none", description="'none' | 'partial' | 'full'")
    unsupported_claims: List[str] = []
    claim_evidence: List[FlaggedClaim] = Field(
        default=[], description="Per-claim breakdown with supporting/contradicting evidence and reasoning"
    )


class EvaluationResult(BaseModel):
    question: str
    ai_response: str
    relevance: JudgeResult
    accuracy: JudgeResult
    hallucination: HallucinationResult
    completeness: JudgeResult
    overall_score: float
    verdict: str
    improvement_suggestions: List[str] = []
