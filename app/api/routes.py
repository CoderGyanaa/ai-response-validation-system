from fastapi import APIRouter, HTTPException

from app.models.schemas import EvaluationRequest, EvaluationResult
from app.evaluation.service import EvaluationService
from app.services.results_store import ResultsStore

router = APIRouter()
evaluation_service = EvaluationService()
results_store = ResultsStore()


@router.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


@router.post("/evaluate", response_model=EvaluationResult)
def evaluate(request: EvaluationRequest) -> EvaluationResult:
    try:
        result = evaluation_service.submit_evaluation(request)
        results_store.save(result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
