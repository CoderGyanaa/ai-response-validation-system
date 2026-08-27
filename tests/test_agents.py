from unittest.mock import patch

from app.models.schemas import EvaluationRequest
from app.agents.relevance import RelevanceJudgeAgent
from app.agents.accuracy import AccuracyJudgeAgent
from app.agents.hallucination import HallucinationDetectionAgent
from app.agents.completeness import CompletenessJudgeAgent
from app.agents.verdict import VerdictAgent

REQUEST = EvaluationRequest(
    question="What is the capital of France?",
    ai_response="Paris.",
)


@patch("app.services.llm_client.LLMClient.complete")
def test_relevance_agent_parses_clean_json(mock_complete):
    mock_complete.return_value = '{"score": 0.9, "reason": "Directly relevant."}'
    agent = RelevanceJudgeAgent()
    result = agent.evaluate(REQUEST, [])
    assert result.score == 0.9
    assert result.agent_name == "relevance"


@patch("app.services.llm_client.LLMClient.complete")
def test_accuracy_agent_uses_evidence(mock_complete):
    mock_complete.return_value = '{"score": 0.7, "reason": "Mostly accurate."}'
    agent = AccuracyJudgeAgent()
    result = agent.evaluate(REQUEST, ["Paris is the capital of France."])
    assert result.score == 0.7
    assert result.evidence == ["Paris is the capital of France."]


@patch("app.services.llm_client.LLMClient.complete")
def test_hallucination_agent_parses_markdown_fenced_json(mock_complete):
    mock_complete.return_value = (
        '```json\n{"score": 0.5, "hallucination_detected": true, '
        '"unsupported_claims": ["fake claim"], "reason": "One unsupported claim."}\n```'
    )
    agent = HallucinationDetectionAgent()
    result = agent.evaluate(REQUEST, ["some evidence"])
    assert result.hallucination_detected is True
    assert result.unsupported_claims == ["fake claim"]


@patch("app.services.llm_client.LLMClient.complete")
def test_completeness_agent_parses_clean_json(mock_complete):
    mock_complete.return_value = '{"score": 1.0, "reason": "Fully answers the question."}'
    agent = CompletenessJudgeAgent()
    result = agent.evaluate(REQUEST, [])
    assert result.score == 1.0


@patch("app.services.llm_client.LLMClient.complete")
def test_agent_fails_gracefully_on_bad_llm_output(mock_complete):
    mock_complete.return_value = "I cannot help with that."
    agent = RelevanceJudgeAgent()
    result = agent.evaluate(REQUEST, [])
    assert result.score == 0.0
    assert "internal error" in result.reason


def test_verdict_agent_aggregates_scores():
    from app.models.schemas import JudgeResult, HallucinationResult

    relevance = JudgeResult(agent_name="relevance", score=0.9, reason="r")
    accuracy = JudgeResult(agent_name="accuracy", score=0.9, reason="r")
    hallucination = HallucinationResult(
        agent_name="hallucination", score=0.9, reason="r",
        hallucination_detected=False, unsupported_claims=[],
    )
    completeness = JudgeResult(agent_name="completeness", score=0.9, reason="r")

    verdict_agent = VerdictAgent()
    overall, verdict, suggestions = verdict_agent.aggregate(
        relevance, accuracy, hallucination, completeness
    )
    assert overall > 0.8
    assert verdict == "PASS"
    assert suggestions == []


def test_verdict_agent_flags_hallucination_suggestion():
    from app.models.schemas import JudgeResult, HallucinationResult

    relevance = JudgeResult(agent_name="relevance", score=0.9, reason="r")
    accuracy = JudgeResult(agent_name="accuracy", score=0.5, reason="r")
    hallucination = HallucinationResult(
        agent_name="hallucination", score=0.2, reason="r",
        hallucination_detected=True, unsupported_claims=["bad claim"],
    )
    completeness = JudgeResult(agent_name="completeness", score=0.9, reason="r")

    verdict_agent = VerdictAgent()
    overall, verdict, suggestions = verdict_agent.aggregate(
        relevance, accuracy, hallucination, completeness
    )
    assert any("unsupported claims" in s.lower() for s in suggestions)
