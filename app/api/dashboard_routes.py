"""
Evaluation Scoring Dashboard API (M4.1).

Every endpoint here reads from ResultsStore — the same persisted data
written by /evaluate and /evaluate/batch — so dashboard numbers are always
generated from real stored evaluation results, never manually entered.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services.results_store import ResultsStore

router = APIRouter()
results_store = ResultsStore()


@router.get("/dashboard/stats")
def get_dashboard_stats(
    verdict: Optional[str] = Query(None, description="Filter: PASS | PARTIAL | FAIL"),
    batch_id: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    max_score: Optional[float] = Query(None, ge=0.0, le=1.0),
) -> dict:
    return results_store.compute_stats(verdict=verdict, batch_id=batch_id, min_score=min_score, max_score=max_score)


@router.get("/dashboard/records")
def get_dashboard_records(
    verdict: Optional[str] = Query(None),
    batch_id: Optional[str] = Query(None),
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    max_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    records = results_store.list_records(
        verdict=verdict, batch_id=batch_id, min_score=min_score, max_score=max_score,
        limit=limit, offset=offset,
    )
    # Trim to summary fields for the table view; full detail is fetched per-record via drill-down.
    summary_records = [
        {
            "id": r["id"], "batch_id": r["batch_id"], "row_number": r["row_number"],
            "created_at": r["created_at"], "question": r["question"],
            "relevance_score": r["relevance_score"], "accuracy_score": r["accuracy_score"],
            "hallucination_score": r["hallucination_score"], "hallucination_status": r["hallucination_status"],
            "completeness_score": r["completeness_score"], "overall_score": r["overall_score"],
            "verdict": r["verdict"], "verdict_label": r["verdict_label"],
        }
        for r in records
    ]
    return {"records": summary_records, "count": len(summary_records)}


@router.get("/dashboard/records/{record_id}")
def get_dashboard_record_detail(record_id: str) -> dict:
    record = results_store.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found.")
    return record["full_result"]


@router.get("/dashboard/batches")
def get_dashboard_batches() -> dict:
    return {"batches": results_store.list_batches()}
