from fastapi import APIRouter, HTTPException

from app.models.schemas import EvaluationRequest, EvaluationResult
from app.evaluation.service import EvaluationService

router = APIRouter()
evaluation_service = EvaluationService()


@router.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


@router.post("/evaluate", response_model=EvaluationResult)
def evaluate(request: EvaluationRequest) -> EvaluationResult:
    try:
        return evaluation_service.submit_evaluation(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
