"""
Batch Evaluation Module (M3.4).

Reuses the existing EvaluationOrchestrator for every valid row — no
evaluation logic is duplicated here. This module only adds: iterating
rows, catching per-row failures so one bad row can't kill the batch,
and computing aggregate statistics across the batch.
"""
import logging
from typing import Iterator

from app.agents.orchestrator import EvaluationOrchestrator
from app.models.schemas import EvaluationRequest
from app.models.batch_schemas import BatchRecord, BatchSummary

logger = logging.getLogger(__name__)


class BatchEvaluationService:
    def __init__(self) -> None:
        self.orchestrator = EvaluationOrchestrator()

    def evaluate_rows(self, valid_rows: list[tuple[int, EvaluationRequest]]) -> Iterator[BatchRecord]:
        """
        Yields one BatchRecord per row as it completes, so a caller can
        stream real, incremental progress rather than waiting for the
        whole batch. A failure on one row is caught and recorded — it
        does not stop the remaining rows from being evaluated.
        """
        for row_number, request in valid_rows:
            try:
                result = self.orchestrator.run(request)
                yield BatchRecord(row_number=row_number, question=request.question, result=result, error=None)
            except Exception as exc:
                logger.exception("Batch row %d failed evaluation", row_number)
                yield BatchRecord(row_number=row_number, question=request.question, result=None, error=str(exc))

    @staticmethod
    def compute_summary(records: list[BatchRecord], total_records: int, invalid_records: int) -> BatchSummary:
        evaluated = [r for r in records if r.result is not None]
        failed = [r for r in records if r.error is not None]
        n = len(evaluated)

        def avg(fn) -> float:
            return round(sum(fn(r.result) for r in evaluated) / n, 4) if n else 0.0

        pass_count = sum(1 for r in evaluated if r.result.verdict == "PASS")
        needs_improvement_count = sum(1 for r in evaluated if r.result.verdict == "PARTIAL")
        fail_count = sum(1 for r in evaluated if r.result.verdict == "FAIL")
        hallucination_count = sum(1 for r in evaluated if r.result.hallucination.hallucination_detected)

        return BatchSummary(
            total_records=total_records,
            valid_records=len(records),
            invalid_records=invalid_records,
            evaluated_records=n,
            failed_records=len(failed),
            average_relevance=avg(lambda r: r.relevance.score),
            average_accuracy=avg(lambda r: r.accuracy.score),
            average_hallucination=avg(lambda r: r.hallucination.score),
            average_completeness=avg(lambda r: r.completeness.score),
            average_overall=avg(lambda r: r.overall_score),
            pass_count=pass_count,
            needs_improvement_count=needs_improvement_count,
            fail_count=fail_count,
            hallucination_frequency=round(hallucination_count / n, 4) if n else 0.0,
        )
