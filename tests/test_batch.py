import io
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from app.evaluation.csv_parser import parse_batch_csv
from app.evaluation.batch_service import BatchEvaluationService
from app.models.schemas import (
    EvaluationResult, JudgeResult, HallucinationResult, CompletenessResult,
)

client = TestClient(app)


def make_result(overall_score=0.9, verdict="PASS", hallucination_detected=False) -> EvaluationResult:
    return EvaluationResult(
        question="q", ai_response="a",
        relevance=JudgeResult(agent_name="relevance", score=0.9, category="fully_relevant", reason="r"),
        accuracy=JudgeResult(agent_name="accuracy", score=0.9, category="correct", reason="r"),
        hallucination=HallucinationResult(
            agent_name="hallucination", score=0.9 if not hallucination_detected else 0.0, reason="r",
            hallucination_detected=hallucination_detected,
            hallucination_status="full" if hallucination_detected else "none",
        ),
        completeness=CompletenessResult(agent_name="completeness", score=0.9, category="complete", reason="r"),
        overall_score=overall_score, verdict=verdict, verdict_label="Pass" if verdict == "PASS" else verdict,
        major_issues=[], consolidated_summary="s", improvement_suggestions=[],
    )


# ---------- CSV parser unit tests ----------

def test_parse_valid_csv_multiple_records():
    csv_text = (
        "question,ai_response,reference_answer,source_document\n"
        "What is 2+2?,4,4,Math facts\n"
        "Capital of France?,Paris,Paris,Geography facts\n"
    )
    valid, invalid, header_error = parse_batch_csv(csv_text.encode("utf-8"))
    assert header_error is None
    assert len(valid) == 2
    assert len(invalid) == 0
    assert valid[0][1].question == "What is 2+2?"
    assert valid[1][1].reference_answer == "Paris"


def test_parse_missing_required_column():
    csv_text = "question,reference_answer\nWhat is 2+2?,4\n"
    valid, invalid, header_error = parse_batch_csv(csv_text.encode("utf-8"))
    assert header_error is not None
    assert "ai_response" in header_error
    assert valid == []
    assert invalid == []


def test_parse_empty_required_field():
    csv_text = "question,ai_response\n,4\nWhat is 2+2?,\n"
    valid, invalid, header_error = parse_batch_csv(csv_text.encode("utf-8"))
    assert header_error is None
    assert len(valid) == 0
    assert len(invalid) == 2
    assert "question" in invalid[0].reason
    assert "ai_response" in invalid[1].reason


def test_parse_malformed_row_short_columns():
    # Row 2 has fewer columns than the header -> ai_response missing -> invalid, not a crash.
    csv_text = "question,ai_response,reference_answer\nWhat is 2+2?\nCapital of France?,Paris,Paris\n"
    valid, invalid, header_error = parse_batch_csv(csv_text.encode("utf-8"))
    assert header_error is None
    assert len(valid) == 1
    assert len(invalid) == 1
    assert invalid[0].row_number == 1


def test_parse_optional_fields_may_be_blank():
    csv_text = "question,ai_response,reference_answer,source_document\nWhat is 2+2?,4,,\n"
    valid, invalid, header_error = parse_batch_csv(csv_text.encode("utf-8"))
    assert header_error is None
    assert len(valid) == 1
    assert valid[0][1].reference_answer is None
    assert valid[0][1].source_document is None


def test_parse_one_invalid_row_does_not_block_others():
    csv_text = (
        "question,ai_response\n"
        "Valid one?,yes\n"
        ",missing question\n"
        "Valid two?,also yes\n"
    )
    valid, invalid, header_error = parse_batch_csv(csv_text.encode("utf-8"))
    assert header_error is None
    assert len(valid) == 2
    assert len(invalid) == 1
    assert invalid[0].row_number == 2


# ---------- Batch service tests (mocked orchestrator) ----------

@patch("app.agents.orchestrator.EvaluationOrchestrator.run")
def test_batch_service_evaluates_all_valid_rows(mock_run):
    mock_run.return_value = make_result()
    service = BatchEvaluationService()
    rows = [(1, __import__("app.models.schemas", fromlist=["EvaluationRequest"]).EvaluationRequest(question="q1", ai_response="a1")),
            (2, __import__("app.models.schemas", fromlist=["EvaluationRequest"]).EvaluationRequest(question="q2", ai_response="a2"))]
    records = list(service.evaluate_rows(rows))
    assert len(records) == 2
    assert all(r.result is not None and r.error is None for r in records)


@patch("app.agents.orchestrator.EvaluationOrchestrator.run")
def test_batch_service_handles_one_row_failure_without_stopping(mock_run):
    from app.models.schemas import EvaluationRequest
    mock_run.side_effect = [make_result(), Exception("simulated LLM crash"), make_result()]
    service = BatchEvaluationService()
    rows = [(1, EvaluationRequest(question="q1", ai_response="a1")),
            (2, EvaluationRequest(question="q2", ai_response="a2")),
            (3, EvaluationRequest(question="q3", ai_response="a3"))]
    records = list(service.evaluate_rows(rows))
    assert len(records) == 3
    assert records[0].error is None
    assert records[1].error == "simulated LLM crash"
    assert records[1].result is None
    assert records[2].error is None  # batch continued after the failure


def test_batch_summary_aggregation():
    from app.models.batch_schemas import BatchRecord
    records = [
        BatchRecord(row_number=1, question="q1", result=make_result(overall_score=1.0, verdict="PASS")),
        BatchRecord(row_number=2, question="q2", result=make_result(overall_score=0.4, verdict="FAIL", hallucination_detected=True)),
        BatchRecord(row_number=3, question="q3", error="boom"),
    ]
    summary = BatchEvaluationService.compute_summary(records, total_records=4, invalid_records=1)
    assert summary.total_records == 4
    assert summary.valid_records == 3
    assert summary.invalid_records == 1
    assert summary.evaluated_records == 2
    assert summary.failed_records == 1
    assert summary.pass_count == 1
    assert summary.fail_count == 1
    assert summary.hallucination_frequency == 0.5
    assert 0.6 < summary.average_overall < 0.8  # (1.0 + 0.4) / 2 = 0.7


def test_batch_summary_handles_zero_evaluated_records():
    summary = BatchEvaluationService.compute_summary([], total_records=0, invalid_records=0)
    assert summary.evaluated_records == 0
    assert summary.average_overall == 0.0
    assert summary.hallucination_frequency == 0.0


# ---------- API endpoint tests ----------

def test_batch_endpoint_rejects_non_csv_file():
    response = client.post(
        "/evaluate/batch",
        files={"file": ("test.txt", io.BytesIO(b"not a csv"), "text/plain")},
    )
    assert response.status_code == 400
    assert "csv" in response.json()["detail"].lower()


def test_batch_endpoint_rejects_missing_required_column():
    csv_bytes = b"question,reference_answer\nWhat is 2+2?,4\n"
    response = client.post(
        "/evaluate/batch",
        files={"file": ("test.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert response.status_code == 400
    assert "ai_response" in response.json()["detail"]


@patch("app.agents.orchestrator.EvaluationOrchestrator.run")
def test_batch_endpoint_streams_full_batch(mock_run):
    mock_run.return_value = make_result()
    csv_bytes = (
        b"question,ai_response,reference_answer,source_document\n"
        b"Valid question?,Valid answer,ref,src\n"
        b",Missing question\n"
    )
    response = client.post(
        "/evaluate/batch",
        files={"file": ("test.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert response.status_code == 200
    lines = [line for line in response.text.strip().split("\n") if line]
    import json
    messages = [json.loads(line) for line in lines]

    init_msg = next(m for m in messages if m["type"] == "init")
    assert init_msg["valid_records"] == 1
    assert init_msg["invalid_records"] == 1

    progress_msgs = [m for m in messages if m["type"] == "progress"]
    assert len(progress_msgs) == 1
    assert progress_msgs[0]["record"]["result"] is not None

    summary_msg = next(m for m in messages if m["type"] == "summary")
    assert summary_msg["summary"]["evaluated_records"] == 1
    assert summary_msg["summary"]["invalid_records"] == 1
