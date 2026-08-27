import logging

from app.models.schemas import EvaluationRequest, EvaluationResult
from app.agents.relevance import RelevanceJudgeAgent
from app.agents.accuracy import AccuracyJudgeAgent
from app.agents.hallucination import HallucinationDetectionAgent
from app.agents.completeness import CompletenessJudgeAgent
from app.agents.verdict import VerdictAgent
from app.retrieval.retriever import Retriever

logger = logging.getLogger(__name__)


class EvaluationOrchestrator:
    """
    Coordinates the full evaluation pipeline:
    retrieve evidence -> run judge agents -> aggregate verdict.
    """

    def __init__(self) -> None:
        self.retriever = Retriever()
        self.relevance_agent = RelevanceJudgeAgent()
        self.accuracy_agent = AccuracyJudgeAgent()
        self.hallucination_agent = HallucinationDetectionAgent()
        self.completeness_agent = CompletenessJudgeAgent()
        self.verdict_agent = VerdictAgent()

    def run(self, request: EvaluationRequest) -> EvaluationResult:
        logger.info("Starting evaluation for question: %s", request.question[:80])

        evidence = self.retriever.retrieve(request.question, request.source_document)

        relevance = self.relevance_agent.evaluate(request, evidence)
        accuracy = self.accuracy_agent.evaluate(request, evidence)
        hallucination = self.hallucination_agent.evaluate(request, evidence)
        completeness = self.completeness_agent.evaluate(request, evidence)

        overall, verdict, suggestions = self.verdict_agent.aggregate(
            relevance, accuracy, hallucination, completeness
        )

        return EvaluationResult(
            question=request.question,
            ai_response=request.ai_response,
            relevance=relevance,
            accuracy=accuracy,
            hallucination=hallucination,
            completeness=completeness,
            overall_score=overall,
            verdict=verdict,
            improvement_suggestions=suggestions,
        )
