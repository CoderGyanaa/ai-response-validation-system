import tempfile
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from app.services.results_store import ResultsStore
from app.models.schemas import EvaluationResult, JudgeResult, HallucinationResult, CompletenessResult

client = TestClient(app)


def make_result(overall_score=0.9, verdict="PASS", relevance=0.9, accuracy=0.9,
                 hallucination_score=0.9, hallucination_detected=False,
                 completeness=0.9, missing_aspects=None) -> EvaluationResult:
    return EvaluationResult(
        question="What is the capital of France?", ai_response="Paris.",
        relevance=JudgeResult(agent_name="relevance", score=relevance, category="fully_relevant", reason="r"),
        accuracy=JudgeResult(agent_name="accuracy", score=accuracy, category="correct", reason="r"),
        hallucination=HallucinationResult(
            agent_name="hallucination", score=hallucination_score, reason="r",
            hallucination_detected=hallucination_detected,
            hallucination_status="full" if hallucination_detected else "none",
        ),
        completeness=CompletenessResult(
            agent_name="completeness", score=completeness, category="complete", reason="r",
            missing_aspects=missing_aspects or [],
        ),
        overall_score=overall_score, verdict=verdict,
        verdict_label={"PASS": "Pass", "PARTIAL": "Needs Improvement", "FAIL": "Fail"}[verdict],
        major_issues=[], consolidated_summary="s", improvement_suggestions=[],
    )


def temp_store() -> ResultsStore:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)  # let ResultsStore create it fresh
    return ResultsStore(db_path=path)


# ---------- ResultsStore unit tests ----------

def test_store_save_and_get_record():
    store = temp_store()
    result = make_result()
    record_id = store.save(result)
    record = store.get_record(record_id)
    assert record is not None
    assert record["question"] == "What is the capital of France?"
    assert record["overall_score"] == 0.9
    assert record["full_result"]["verdict"] == "PASS"


def test_store_get_nonexistent_record_returns_none():
    store = temp_store()
    assert store.get_record("does-not-exist") is None


def test_store_list_records_filters_by_verdict():
    store = temp_store()
    store.save(make_result(verdict="PASS"))
    store.save(make_result(verdict="FAIL", overall_score=0.2))
    records = store.list_records(verdict="FAIL")
    assert len(records) == 1
    assert records[0]["verdict"] == "FAIL"


def test_store_list_records_filters_by_score_range():
    store = temp_store()
    store.save(make_result(overall_score=0.9))
    store.save(make_result(overall_score=0.3))
    records = store.list_records(min_score=0.5)
    assert len(records) == 1
    assert records[0]["overall_score"] == 0.9


def test_store_batch_grouping():
    store = temp_store()
    batch_id = store.new_batch_id()
    store.save(make_result(), batch_id=batch_id, row_number=1)
    store.save(make_result(), batch_id=batch_id, row_number=2)
    store.save(make_result())  # single eval, no batch

    batch_records = store.list_records(batch_id=batch_id)
    assert len(batch_records) == 2

    batches = store.list_batches()
    assert len(batches) == 1
    assert batches[0]["record_count"] == 2


def test_store_compute_stats_matches_underlying_records():
    store = temp_store()
    store.save(make_result(overall_score=1.0, verdict="PASS", relevance=1.0, accuracy=1.0, completeness=1.0))
    store.save(make_result(overall_score=0.2, verdict="FAIL", hallucination_detected=True, hallucination_score=0.0))
    store.save(make_result(overall_score=0.6, verdict="PARTIAL", missing_aspects=["aspect one"]))

    stats = store.compute_stats()
    assert stats["total_records"] == 3
    assert stats["pass_count"] == 1
    assert stats["fail_count"] == 1
    assert stats["needs_improvement_count"] == 1
    assert stats["hallucination_count"] == 1
    assert abs(stats["hallucination_frequency"] - (1 / 3)) < 0.001
    assert stats["records_with_missing_aspects"] == 1
    assert abs(stats["average_overall"] - (1.0 + 0.2 + 0.6) / 3) < 0.001
    assert sum(stats["score_distribution"].values()) == 3


def test_store_compute_stats_empty_returns_zeros_not_crash():
    store = temp_store()
    stats = store.compute_stats()
    assert stats["total_records"] == 0
    assert stats["average_overall"] == 0.0
    assert stats["hallucination_frequency"] == 0.0


def test_store_top_issues_reflects_actual_records():
    store = temp_store()
    store.save(make_result(accuracy=0.2, overall_score=0.4, verdict="FAIL"))
    store.save(make_result(accuracy=0.1, overall_score=0.3, verdict="FAIL"))
    store.save(make_result())  # clean record, no issues

    stats = store.compute_stats()
    issue_names = [i["issue"] for i in stats["top_issues"]]
    assert "Low accuracy" in issue_names
    low_accuracy_entry = next(i for i in stats["top_issues"] if i["issue"] == "Low accuracy")
    assert low_accuracy_entry["count"] == 2


# ---------- Dashboard API tests (using the app's real store; verify it doesn't crash) ----------

def test_dashboard_stats_endpoint_returns_valid_shape():
    response = client.get("/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_records" in data
    assert "average_overall" in data
    assert "score_distribution" in data


def test_dashboard_records_endpoint_returns_valid_shape():
    response = client.get("/dashboard/records")
    assert response.status_code == 200
    data = response.json()
    assert "records" in data
    assert "count" in data


def test_dashboard_record_detail_404_for_missing_id():
    response = client.get("/dashboard/records/nonexistent-id-xyz")
    assert response.status_code == 404


def test_dashboard_batches_endpoint_returns_valid_shape():
    response = client.get("/dashboard/batches")
    assert response.status_code == 200
    assert "batches" in response.json()


@patch("app.evaluation.service.EvaluationOrchestrator.run")
def test_single_evaluate_persists_to_store(mock_run):
    mock_run.return_value = make_result()
    response = client.post("/evaluate", json={"question": "q", "ai_response": "a"})
    assert response.status_code == 200

    records_response = client.get("/dashboard/records", params={"limit": 1})
    assert records_response.json()["count"] >= 1
