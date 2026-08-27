import logging

from app.models.schemas import EvaluationRequest, EvaluationResult
from app.agents.orchestrator import EvaluationOrchestrator

logger = logging.getLogger(__name__)


class EvaluationService:
    def __init__(self) -> None:
        self.orchestrator = EvaluationOrchestrator()

    def submit_evaluation(self, request: EvaluationRequest) -> EvaluationResult:
        # Pydantic already enforces required fields (question, ai_response) and non-empty strings.
        # Add any additional business-rule validation here as the project grows.
        try:
            return self.orchestrator.run(request)
        except Exception:
            logger.exception("Evaluation pipeline failed")
            raise
