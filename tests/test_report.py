import io
import os
import tempfile

import pdfplumber
from fastapi.testclient import TestClient

from main import app
from app.services.results_store import ResultsStore
from app.services.report_generator import generate_batch_report_pdf
from app.models.schemas import (
    EvaluationResult, JudgeResult, HallucinationResult, CompletenessResult, FlaggedClaim,
)

client = TestClient(app)


def temp_store() -> ResultsStore:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    return ResultsStore(db_path=path)


def make_result(question="What is the capital of France?", ai_response="Paris.",
                 overall_score=0.9, verdict="PASS", claims=None, missing=None,
                 accuracy_evidence=None) -> EvaluationResult:
    return EvaluationResult(
        question=question, ai_response=ai_response,
        relevance=JudgeResult(agent_name="relevance", score=0.9, category="fully_relevant", reason="Directly relevant."),
        accuracy=JudgeResult(
            agent_name="accuracy", score=0.8, category="correct", reason="Matches evidence.",
            evidence=accuracy_evidence or [],
        ),
        hallucination=HallucinationResult(
            agent_name="hallucination", score=0.9 if not claims else 0.3, reason="Checked against evidence.",
            hallucination_detected=bool(claims),
            hallucination_status="partial" if claims else "none",
            unsupported_claims=[c["claim"] for c in (claims or [])],
            claim_evidence=[FlaggedClaim(**c) for c in (claims or [])],
        ),
        completeness=CompletenessResult(
            agent_name="completeness", score=0.85, category="complete", reason="Covers the question.",
            missing_aspects=missing or [],
        ),
        overall_score=overall_score, verdict=verdict,
        verdict_label={"PASS": "Pass", "PARTIAL": "Needs Improvement", "FAIL": "Fail"}[verdict],
        major_issues=[], consolidated_summary="Summary text.", improvement_suggestions=[],
    )


# ---------- Report generator unit tests ----------

def test_generate_pdf_returns_valid_pdf_bytes():
    store = temp_store()
    batch_id = store.new_batch_id()
    store.save(make_result(), batch_id=batch_id, row_number=1)

    pdf_bytes = generate_batch_report_pdf(batch_id, store)
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 500


def test_generated_pdf_content_matches_stored_record():
    store = temp_store()
    batch_id = store.new_batch_id()
    store.save(make_result(
        question="What is the capital of Germany?",
        ai_response="Berlin is the capital.",
        overall_score=0.42, verdict="FAIL",
    ), batch_id=batch_id, row_number=1)

    pdf_bytes = generate_batch_report_pdf(batch_id, store)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    assert "What is the capital of Germany?" in text
    assert "Berlin is the capital." in text
    assert "0.42" in text
    assert "Fail" in text


def test_generated_pdf_includes_flagged_claims_and_evidence():
    store = temp_store()
    batch_id = store.new_batch_id()
    store.save(make_result(
        claims=[{
            "claim": "population is 50 million", "supported": False,
            "evidence": ["Actual population is 3.7 million"], "reason": "Contradicted by evidence",
        }],
    ), batch_id=batch_id, row_number=1)

    pdf_bytes = generate_batch_report_pdf(batch_id, store)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    assert "population is 50 million" in text
    assert "Actual population is 3.7 million" in text
    assert "Contradicted by evidence" in text


def test_generated_pdf_includes_missing_aspects():
    store = temp_store()
    batch_id = store.new_batch_id()
    store.save(make_result(missing=["yellow as the third primary color"]), batch_id=batch_id, row_number=1)

    pdf_bytes = generate_batch_report_pdf(batch_id, store)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    assert "yellow as the third primary color" in text


def test_generated_pdf_includes_accuracy_evidence():
    store = temp_store()
    batch_id = store.new_batch_id()
    store.save(make_result(accuracy_evidence=["Paris is the capital of France per official records."]),
               batch_id=batch_id, row_number=1)

    pdf_bytes = generate_batch_report_pdf(batch_id, store)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    assert "Paris is the capital of France per official records." in text


def test_generated_pdf_summary_matches_computed_stats():
    store = temp_store()
    batch_id = store.new_batch_id()
    store.save(make_result(overall_score=1.0, verdict="PASS"), batch_id=batch_id, row_number=1)
    store.save(make_result(overall_score=0.2, verdict="FAIL"), batch_id=batch_id, row_number=2)

    stats = store.compute_stats(batch_id=batch_id)
    pdf_bytes = generate_batch_report_pdf(batch_id, store)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    assert f"{stats['average_overall']:.2f}" in text
    assert str(stats["pass_count"]) in text
    assert str(stats["fail_count"]) in text


def test_pdf_handles_special_characters_without_crashing():
    store = temp_store()
    batch_id = store.new_batch_id()
    store.save(make_result(
        question="What is <b>2</b> & 2?",
        ai_response="The answer is 4 & that's <final>.",
    ), batch_id=batch_id, row_number=1)

    # Must not raise — reportlab's markup parser would choke on unescaped &, <, >
    pdf_bytes = generate_batch_report_pdf(batch_id, store)
    assert pdf_bytes[:4] == b"%PDF"
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "2</b> & 2" in text or "2 & 2" in text  # rendered as literal text, not parsed as markup


def test_pdf_handles_long_content_across_multiple_pages():
    store = temp_store()
    batch_id = store.new_batch_id()
    long_text = "This is a long response. " * 60
    store.save(make_result(ai_response=long_text, missing=[f"aspect {i}" for i in range(15)]),
               batch_id=batch_id, row_number=1)

    pdf_bytes = generate_batch_report_pdf(batch_id, store)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        assert len(pdf.pages) >= 2


def test_pdf_generation_for_batch_with_no_flagged_claims():
    store = temp_store()
    batch_id = store.new_batch_id()
    store.save(make_result(), batch_id=batch_id, row_number=1)

    pdf_bytes = generate_batch_report_pdf(batch_id, store)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "No unsupported claims detected." in text


def test_pdf_generation_for_empty_batch_does_not_crash():
    store = temp_store()
    batch_id = store.new_batch_id()  # no records saved under this batch
    pdf_bytes = generate_batch_report_pdf(batch_id, store)
    assert pdf_bytes[:4] == b"%PDF"


# ---------- API endpoint tests ----------

def test_report_endpoint_returns_pdf_for_existing_batch(monkeypatch):
    # Use the app's real results_store instance so the endpoint sees our saved data.
    from app.api import report_routes
    batch_id = report_routes.results_store.new_batch_id()
    report_routes.results_store.save(make_result(), batch_id=batch_id, row_number=1)

    response = client.get(f"/reports/batch/{batch_id}/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"
    assert "attachment" in response.headers["content-disposition"]


def test_report_endpoint_404_for_nonexistent_batch():
    response = client.get("/reports/batch/nonexistent-batch-id/pdf")
    assert response.status_code == 404
