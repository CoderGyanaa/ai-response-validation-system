"""
Schemas for the Batch Evaluation Module (M3.4).
Kept in a separate file from app/models/schemas.py so the existing
M1/M2/M3.1/M3.2 schemas are never touched by this feature.
"""
from typing import Optional, List
from pydantic import BaseModel, Field

from app.models.schemas import EvaluationResult


class BatchRowError(BaseModel):
    """A CSV row rejected before evaluation (missing/empty required field, malformed row)."""
    row_number: int
    reason: str


class BatchRecord(BaseModel):
    """One row that passed CSV validation and was sent through the Evaluation Orchestrator."""
    row_number: int
    question: str = ""
    result: Optional[EvaluationResult] = None
    error: Optional[str] = Field(None, description="Set if evaluation itself failed after CSV validation passed")


class BatchSummary(BaseModel):
    total_records: int
    valid_records: int
    invalid_records: int
    evaluated_records: int
    failed_records: int
    average_relevance: float = 0.0
    average_accuracy: float = 0.0
    average_hallucination: float = 0.0
    average_completeness: float = 0.0
    average_overall: float = 0.0
    pass_count: int = 0
    needs_improvement_count: int = 0
    fail_count: int = 0
    hallucination_frequency: float = 0.0
