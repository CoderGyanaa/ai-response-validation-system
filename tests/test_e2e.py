"""
M4.3 - End-to-end testing & system validation.

Real code under test: agents, orchestrator, verdict agent, results store,
FastAPI routes, dashboard endpoints, PDF generator.
Replaced: the Gemini call (FakeLLM) and the vector-store query (FakeRetrieval)
- see tests/e2e_support.py for why, and for what these tests therefore do NOT
prove (they validate wiring/math/persistence/consistency, not Gemini's judgment).
"""
import csv
import io
import json
import sqlite3

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from main import app
from app.api import routes, batch_routes, dashboard_routes, report_routes
from app.agents.completeness import CompletenessJudgeAgent
from app.agents.hallucination import HallucinationDetectionAgent
from app.agents.orchestrator import EvaluationOrchestrator
from app.agents.verdict import VerdictAgent
from app.models.schemas import (
    EvaluationRequest, JudgeResult, HallucinationResult, CompletenessResult, EvaluationResult, FlaggedClaim,
)
from app.retrieval.retriever import Retriever
from app.services.llm_client import LLMClient
from app.services.results_store import ResultsStore
from tests.e2e_support import (
    SCENARIOS, FakeLLM, FakeRetrieval, independent_weighted,
    REL_CATS, ACC_CATS, HAL_STATUSES, COMP_CATS, VERDICT_LABELS,
)

ALL = list(SCENARIOS)


# ----------------------------------------------------------------------------
# Fixtures / helpers
# ----------------------------------------------------------------------------

class Env:
    pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Isolated store shared by every router + scripted LLM + scripted retrieval."""
    e = Env()
    e.store = ResultsStore(str(tmp_path / "e2e.db"))
    for mod in (routes, batch_routes, dashboard_routes, report_routes):
        monkeypatch.setattr(mod, "results_store", e.store)

    e.llm, e.rag = FakeLLM(), FakeRetrieval()
    e.real_retrieve = Retriever.retrieve
    monkeypatch.setattr(LLMClient, "complete", lambda self, prompt, max_tokens=1000: e.llm(self, prompt, max_tokens))
    monkeypatch.setattr(Retriever, "retrieve",
                        lambda self, question, source_document=None, top_k=5: e.rag(self, question, source_document, top_k))
    e.client = TestClient(app)
    return e


def payload_for(name):
    sc = SCENARIOS[name]
    p = {"question": sc["question"], "ai_response": sc["ai_response"]}
    if sc["reference"]:
        p["reference_answer"] = sc["reference"]
    return p


def post_single(env, name):
    resp = env.client.post("/evaluate", json=payload_for(name))
    assert resp.status_code == 200, resp.text
    return resp.json()


def assert_valid_result(body):
    """Cross-field invariants every stored/returned result must satisfy."""
    for dim in ("relevance", "accuracy", "hallucination", "completeness"):
        assert 0.0 <= body[dim]["score"] <= 1.0
        assert body[dim]["reason"].strip(), f"{dim} has no reasoning"
    assert body["relevance"]["category"] in REL_CATS
    assert body["accuracy"]["category"] in ACC_CATS
    assert body["hallucination"]["hallucination_status"] in HAL_STATUSES
    assert body["completeness"]["category"] in COMP_CATS
    assert 0.0 <= body["overall_score"] <= 1.0
    assert body["verdict_label"] == VERDICT_LABELS[body["verdict"]]
    assert body["consolidated_summary"].strip()

    h = body["hallucination"]
    if h["hallucination_detected"]:
        assert h["hallucination_status"] in ("partial", "full")
        assert len(h["claim_evidence"]) > 0
        assert h["unsupported_claims"] == [c["claim"] for c in h["claim_evidence"]]
    else:
        assert h["claim_evidence"] == [] and h["unsupported_claims"] == []
    if h["hallucination_status"] == "full":
        assert body["verdict"] == "FAIL"

    c = body["completeness"]
    if c["missing_aspects"]:
        assert c["category"] != "complete"
    if c["category"] == "complete":
        assert c["score"] >= 0.8


def csv_bytes(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["question", "ai_response", "reference_answer", "source_document"])
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def post_batch(env, raw, filename="batch.csv"):
    return env.client.post("/evaluate/batch", files={"file": (filename, io.BytesIO(raw), "text/csv")})


def ndjson(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def pdf_text(pdf_bytes):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = len(pdf.pages)
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    return " ".join(text.split()), pages


def sql_one(db_path, query, params=()):
    with sqlite3.connect(db_path) as c:
        return c.execute(query, params).fetchone()[0]


def row_for(name, reference=True):
    sc = SCENARIOS[name]
    return (sc["question"], sc["ai_response"], (sc["reference"] or "") if reference else "", "")


# ----------------------------------------------------------------------------
# 1. Single-evaluation end-to-end (scenarios A-H plus extras)
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("name", ALL)
def test_single_evaluation_end_to_end(env, name):
    sc = SCENARIOS[name]
    llm = sc["llm"]
    body = post_single(env, name)
    assert_valid_result(body)

    # judge outputs flow through unchanged
    for dim in ("relevance", "accuracy"):
        assert body[dim]["score"] == llm[dim]["score"]
        assert body[dim]["category"] == llm[dim]["category"]
    assert body["hallucination"]["score"] == llm["hallucination"]["score"]
    assert body["hallucination"]["hallucination_status"] == llm["hallucination"]["hallucination_status"]
    assert body["completeness"]["score"] == llm["completeness"]["score"]

    # weighted score: hand-calculated literal AND independent recomputation
    assert body["overall_score"] == pytest.approx(sc["expected_overall"], abs=1e-6)
    assert body["overall_score"] == pytest.approx(independent_weighted(llm), abs=1e-6)
    assert body["verdict"] == sc["expected_verdict"]

    # evidence, claims, aspects preserved
    assert body["accuracy"]["evidence"] == sc["evidence"][:3]
    assert body["hallucination"]["evidence"] == sc["evidence"][:3]
    claims = llm["hallucination"]["claims"]
    assert [(c["claim"], c["evidence"], c["reason"]) for c in body["hallucination"]["claim_evidence"]] == \
        [(c["claim"], c["evidence"], c["reason"]) for c in claims]
    assert body["completeness"]["addressed_aspects"] == llm["completeness"]["addressed_aspects"]
    assert body["completeness"]["missing_aspects"] == llm["completeness"]["missing_aspects"]

    # persisted, and drill-down returns exactly what the user saw
    records = env.client.get("/dashboard/records").json()["records"]
    assert len(records) == 1
    assert records[0]["batch_id"] is None
    assert records[0]["verdict"] == sc["expected_verdict"]
    detail = env.client.get(f"/dashboard/records/{records[0]['id']}")
    assert detail.status_code == 200
    assert detail.json() == body


def test_all_four_judges_are_called_once_per_evaluation(env):
    post_single(env, "A_correct")
    assert sorted(a for a, _ in env.llm.prompts) == ["accuracy", "completeness", "hallucination", "relevance"]


def test_no_reference_answer_evaluation_uses_retrieved_evidence(env):
    sc = SCENARIOS["H_no_reference"]
    assert "reference_answer" not in payload_for("H_no_reference")
    body = post_single(env, "H_no_reference")
    assert body["verdict"] == "PASS"
    for agent in ("accuracy", "hallucination", "completeness"):
        prompt = env.llm.prompt_for(agent)
        assert sc["evidence"][0] in prompt, f"{agent} agent never received the retrieved evidence"
    assert "(not provided)" in env.llm.prompt_for("accuracy")
    assert "(not provided)" in env.llm.prompt_for("completeness")


def test_user_supplied_source_document_is_passed_to_agents_as_evidence(env):
    payload = payload_for("H_no_reference")
    payload["source_document"] = "USER SUPPLIED SOURCE TEXT"
    assert env.client.post("/evaluate", json=payload).status_code == 200
    assert "USER SUPPLIED SOURCE TEXT" in env.llm.prompt_for("hallucination")


def test_evaluation_with_empty_retrieval_still_completes_and_persists(env):
    env.rag.enabled = False
    body = post_single(env, "A_correct")
    assert_valid_result(body)
    assert body["accuracy"]["evidence"] == []
    assert "(no evidence retrieved)" in env.llm.prompt_for("hallucination")
    assert len(env.client.get("/dashboard/records").json()["records"]) == 1


def test_identical_input_gives_identical_result_when_judges_are_deterministic(env):
    first, second = post_single(env, "C_partially_correct"), post_single(env, "C_partially_correct")
    assert first == second
    assert env.client.get("/dashboard/stats").json()["total_records"] == 2


def test_single_evaluation_has_no_pdf_export(env):
    """PDF export is batch-scoped (M4.2). Documenting the behavior for single evaluations."""
    post_single(env, "A_correct")
    record_id = env.client.get("/dashboard/records").json()["records"][0]["id"]
    assert env.client.get(f"/reports/batch/{record_id}/pdf").status_code == 404


def test_end_to_end_with_real_vector_store_retrieval(env, tmp_path, monkeypatch):
    """Full RAG path: real ChromaDB + real embeddings -> real Retriever -> agents.
    Skipped where chromadb/sentence-transformers are unavailable."""
    pytest.importorskip("chromadb")
    pytest.importorskip("sentence_transformers")
    from app.config.settings import settings
    from app.services.vector_store import VectorStore

    scenario = {
        "question": "Which city is the capital of France according to the knowledge base?",
        "ai_response": "Paris is the capital city of France, per the knowledge base.",
        "reference": None, "evidence": [],
        "llm": SCENARIOS["A_correct"]["llm"],
    }
    monkeypatch.setitem(SCENARIOS, "R_real_rag", scenario)
    monkeypatch.setattr(settings, "VECTOR_DB_PATH", str(tmp_path / "chroma_e2e"))
    vs = VectorStore()
    vs.add(
        ids=["d1", "d2"],
        documents=["Q: Which city is the capital of France?\nA: Paris is the capital of France.",
                   "Q: Which city is the capital of Germany?\nA: Berlin is the capital of Germany."],
        metadatas=[{"dataset": "e2e"}, {"dataset": "e2e"}],
    )
    monkeypatch.setattr(Retriever, "retrieve", env.real_retrieve)
    monkeypatch.setattr(routes.evaluation_service, "orchestrator", EvaluationOrchestrator())

    resp = env.client.post("/evaluate", json={"question": scenario["question"], "ai_response": scenario["ai_response"]})
    assert resp.status_code == 200, resp.text
    assert any("Paris" in e for e in resp.json()["hallucination"]["evidence"])
    assert "Paris" in env.llm.prompt_for("hallucination")


# ----------------------------------------------------------------------------
# 2. Batch end-to-end
# ----------------------------------------------------------------------------

BATCH_ROWS = [
    row_for("A_correct"),                                            # 1  valid
    row_for("B_incorrect"),                                          # 2  valid
    row_for("C_partially_correct"),                                  # 3  valid
    row_for("D_incomplete"),                                         # 4  valid
    ("", "An answer that has no question", "", ""),                  # 5  invalid: empty question
    row_for("G_mixed", reference=False),                             # 6  valid
    ("A question that has no response", "", "", ""),                 # 7  invalid: empty response
    row_for("F_unsupported", reference=False),                       # 8  valid
    ("Only one column present in this row",),                        # 9  invalid: malformed (short) row
    row_for("E_off_topic"),                                          # 10 valid
    row_for("Z_special_chars", reference=False),                     # 11 valid
]
VALID_ROWS = {1: "A_correct", 2: "B_incorrect", 3: "C_partially_correct", 4: "D_incomplete",
              6: "G_mixed", 8: "F_unsupported", 10: "E_off_topic", 11: "Z_special_chars"}
INVALID_ROWS = {5, 7, 9}

# Hand-calculated from the scenario table in tests/e2e_support.py (8 valid records)
EXPECTED_BATCH_STATS = {
    "total_records": 8, "pass_count": 2, "needs_improvement_count": 4, "fail_count": 2,
    "pass_pct": 25.0, "needs_improvement_pct": 50.0, "fail_pct": 25.0,
    "average_relevance": 0.825, "average_accuracy": 0.5625, "average_hallucination": 0.675,
    "average_completeness": 0.7875, "average_overall": 0.643125,
    "hallucination_count": 4, "hallucination_frequency": 0.5,
    "records_with_missing_aspects": 2, "missing_aspects_frequency": 0.25,
    "score_distribution": {"0.0-0.2": 0, "0.2-0.4": 1, "0.4-0.6": 3, "0.6-0.8": 2, "0.8-1.0": 2},
}
EXPECTED_TOP_ISSUES = {"Hallucinated claims": 4, "Low accuracy": 2, "Incomplete response": 2, "Low relevance": 1}


def assert_stats_match(stats, expected):
    for key, value in expected.items():
        if isinstance(value, float):
            assert stats[key] == pytest.approx(value, abs=1e-4), key
        else:
            assert stats[key] == value, key


def run_full_batch(env):
    resp = post_batch(env, csv_bytes(BATCH_ROWS))
    assert resp.status_code == 200
    return ndjson(resp)


def test_batch_end_to_end_stream_counts_and_isolation_of_invalid_rows(env):
    msgs = run_full_batch(env)
    init = next(m for m in msgs if m["type"] == "init")
    assert (init["total_records"], init["valid_records"], init["invalid_records"]) == (11, 8, 3)
    assert {r["row_number"] for r in init["invalid_rows"]} == INVALID_ROWS
    reasons = {r["row_number"]: r["reason"] for r in init["invalid_rows"]}
    assert "question" in reasons[5] and "ai_response" in reasons[7] and "ai_response" in reasons[9]

    progress = [m for m in msgs if m["type"] == "progress"]
    assert len(progress) == 8
    assert [m["completed"] for m in progress] == list(range(1, 9))
    assert {m["record"]["row_number"] for m in progress} == set(VALID_ROWS)
    for m in progress:
        rec = m["record"]
        assert rec["error"] is None
        assert_valid_result(rec["result"])
        assert rec["result"]["verdict"] == SCENARIOS[VALID_ROWS[rec["row_number"]]]["expected_verdict"]

    summary = next(m for m in msgs if m["type"] == "summary")["summary"]
    assert (summary["total_records"], summary["valid_records"], summary["invalid_records"]) == (11, 8, 3)
    assert (summary["evaluated_records"], summary["failed_records"]) == (8, 0)


def test_batch_persists_with_shared_batch_id_and_no_rows_for_invalid_records(env):
    msgs = run_full_batch(env)
    batch_id = next(m for m in msgs if m["type"] == "init")["batch_id"]
    assert next(m for m in msgs if m["type"] == "summary")["batch_id"] == batch_id

    records = env.client.get("/dashboard/records", params={"batch_id": batch_id, "limit": 100}).json()["records"]
    assert len(records) == 8
    assert {r["batch_id"] for r in records} == {batch_id}
    assert {r["row_number"] for r in records} == set(VALID_ROWS)
    assert env.client.get("/dashboard/records", params={"limit": 100}).json()["count"] == 8  # nothing saved for invalid rows

    batches = env.client.get("/dashboard/batches").json()["batches"]
    assert len(batches) == 1 and batches[0]["batch_id"] == batch_id and batches[0]["record_count"] == 8


def test_batch_dashboard_statistics_match_hand_calculation_and_independent_sql(env):
    msgs = run_full_batch(env)
    batch_id = next(m for m in msgs if m["type"] == "init")["batch_id"]
    stats = env.client.get("/dashboard/stats", params={"batch_id": batch_id}).json()

    assert_stats_match(stats, EXPECTED_BATCH_STATS)
    assert {i["issue"]: i["count"] for i in stats["top_issues"]} == EXPECTED_TOP_ISSUES
    counts = [i["count"] for i in stats["top_issues"]]
    assert counts == sorted(counts, reverse=True)

    # independent path: raw SQL aggregates against the same database file
    db = env.store.db_path
    assert sql_one(db, "SELECT COUNT(*) FROM evaluation_results WHERE batch_id=?", (batch_id,)) == stats["total_records"]
    assert sql_one(db, "SELECT AVG(overall_score) FROM evaluation_results WHERE batch_id=?", (batch_id,)) == \
        pytest.approx(stats["average_overall"], abs=1e-4)
    assert sql_one(db, "SELECT AVG(accuracy_score) FROM evaluation_results WHERE batch_id=?", (batch_id,)) == \
        pytest.approx(stats["average_accuracy"], abs=1e-4)
    assert sql_one(db, "SELECT SUM(verdict='PASS') FROM evaluation_results WHERE batch_id=?", (batch_id,)) == stats["pass_count"]
    assert sql_one(db, "SELECT SUM(hallucination_detected) FROM evaluation_results WHERE batch_id=?", (batch_id,)) == \
        stats["hallucination_count"]


def test_streamed_batch_summary_agrees_with_dashboard_statistics(env):
    msgs = run_full_batch(env)
    summary = next(m for m in msgs if m["type"] == "summary")["summary"]
    batch_id = next(m for m in msgs if m["type"] == "init")["batch_id"]
    stats = env.client.get("/dashboard/stats", params={"batch_id": batch_id}).json()
    assert summary["pass_count"] == stats["pass_count"]
    assert summary["needs_improvement_count"] == stats["needs_improvement_count"]
    assert summary["fail_count"] == stats["fail_count"]
    assert summary["hallucination_frequency"] == pytest.approx(stats["hallucination_frequency"], abs=1e-4)
    for key in ("relevance", "accuracy", "hallucination", "completeness", "overall"):
        assert summary[f"average_{key}"] == pytest.approx(stats[f"average_{key}"], abs=1e-4), key


def test_batch_drill_down_returns_the_streamed_result_for_every_record(env):
    msgs = run_full_batch(env)
    streamed = {m["record"]["row_number"]: m["record"]["result"] for m in msgs if m["type"] == "progress"}
    batch_id = next(m for m in msgs if m["type"] == "init")["batch_id"]
    for rec in env.client.get("/dashboard/records", params={"batch_id": batch_id, "limit": 100}).json()["records"]:
        detail = env.client.get(f"/dashboard/records/{rec['id']}").json()
        assert detail == streamed[rec["row_number"]]


def test_batch_pdf_matches_dashboard_and_stored_records(env):
    msgs = run_full_batch(env)
    batch_id = next(m for m in msgs if m["type"] == "init")["batch_id"]
    stats = env.client.get("/dashboard/stats", params={"batch_id": batch_id}).json()
    stored = env.client.get("/dashboard/records", params={"batch_id": batch_id, "limit": 100}).json()["records"]

    resp = env.client.get(f"/reports/batch/{batch_id}/pdf")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
    text, pages = pdf_text(resp.content)
    assert pages >= 3

    # summary table == dashboard statistics
    assert f"Batch ID: {batch_id}" in text
    assert f"Records included: {stats['total_records']}" in text
    assert f"Total records evaluated {stats['total_records']}" in text
    assert f"Pass {stats['pass_count']} ({stats['pass_pct']}%)" in text
    assert f"Needs Improvement {stats['needs_improvement_count']} ({stats['needs_improvement_pct']}%)" in text
    assert f"Fail {stats['fail_count']} ({stats['fail_pct']}%)" in text
    for label, key in (("Relevance", "average_relevance"), ("Accuracy", "average_accuracy"),
                       ("Hallucination", "average_hallucination"), ("Completeness", "average_completeness"),
                       ("Overall Score", "average_overall")):
        assert f"Average {label} {stats[key]:.2f}" in text, label
    assert f"Hallucination frequency {stats['hallucination_frequency'] * 100:.1f}%" in text
    assert f"Incomplete-response frequency {stats['missing_aspects_frequency'] * 100:.1f}%" in text

    # recommendations mirror the dashboard's top issues
    for issue in stats["top_issues"]:
        assert f"{issue['issue']} occurred in {issue['count']} of {stats['total_records']} responses" in text

    # every stored record appears with its verdict counts and per-record content
    assert text.count("Verdict: Pass") == stats["pass_count"]
    assert text.count("Verdict: Needs Improvement") == stats["needs_improvement_count"]
    assert text.count("Verdict: Fail") == stats["fail_count"]
    for rec in stored:
        assert f"Overall score: {rec['overall_score']:.2f}" in text
    for name in VALID_ROWS.values():
        sc = SCENARIOS[name]
        assert sc["question"] in text and sc["ai_response"] in text, name
        assert sc["evidence"][0] in text, name                       # accuracy evidence
        for claim in sc["llm"]["hallucination"]["claims"]:           # flagged claims, evidence, reasons
            assert claim["claim"] in text and claim["reason"] in text
            for ev in claim["evidence"]:
                assert ev in text
        for missing in sc["llm"]["completeness"]["missing_aspects"]:
            assert missing in text
    assert text.count("No unsupported claims detected.") == 4      # A, D, E, Z
    for invalid_text in ("An answer that has no question", "A question that has no response"):
        assert invalid_text not in text                            # invalid rows never reach the report


def test_batch_row_failure_does_not_stop_remaining_rows_or_pollute_storage(env, monkeypatch):
    real_run = EvaluationOrchestrator.run

    def flaky(self, request):
        if request.question == SCENARIOS["B_incorrect"]["question"]:
            raise RuntimeError("simulated orchestrator failure")
        return real_run(self, request)

    monkeypatch.setattr(EvaluationOrchestrator, "run", flaky)
    msgs = ndjson(post_batch(env, csv_bytes([row_for("A_correct"), row_for("B_incorrect"), row_for("C_partially_correct")])))

    progress = [m["record"] for m in msgs if m["type"] == "progress"]
    assert [r["row_number"] for r in progress] == [1, 2, 3]
    assert progress[1]["result"] is None and "simulated orchestrator failure" in progress[1]["error"]
    assert progress[0]["error"] is None and progress[2]["error"] is None

    summary = next(m for m in msgs if m["type"] == "summary")["summary"]
    assert (summary["evaluated_records"], summary["failed_records"]) == (2, 1)

    batch_id = next(m for m in msgs if m["type"] == "init")["batch_id"]
    assert env.client.get("/dashboard/stats", params={"batch_id": batch_id}).json()["total_records"] == 2
    text, _ = pdf_text(env.client.get(f"/reports/batch/{batch_id}/pdf").content)
    assert "Records included: 2" in text


def test_two_batches_are_kept_separate_and_combine_in_overall_stats(env):
    first = ndjson(post_batch(env, csv_bytes([row_for("A_correct"), row_for("B_incorrect")])))
    second = ndjson(post_batch(env, csv_bytes([row_for("C_partially_correct")])))
    id1 = next(m for m in first if m["type"] == "init")["batch_id"]
    id2 = next(m for m in second if m["type"] == "init")["batch_id"]
    assert id1 != id2
    assert env.client.get("/dashboard/stats", params={"batch_id": id1}).json()["total_records"] == 2
    assert env.client.get("/dashboard/stats", params={"batch_id": id2}).json()["total_records"] == 1
    assert env.client.get("/dashboard/stats").json()["total_records"] == 3
    assert len(env.client.get("/dashboard/batches").json()["batches"]) == 2


# ----------------------------------------------------------------------------
# 3-5. Hallucination and completeness validation
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("name,status,n_claims,claims_have_evidence", [
    ("A_correct", "none", 0, False),          # completely supported
    ("V_vague", "none", 0, False),            # no obvious unsupported claim
    ("F_unsupported", "partial", 1, False),   # unsupported, nothing in evidence either way
    ("G_mixed", "partial", 1, True),          # supported + unsupported claims together
    ("C_partially_correct", "partial", 1, True),
    ("B_incorrect", "full", 2, True),         # direct contradiction with retrieved evidence
])
def test_hallucination_detection_cases(env, name, status, n_claims, claims_have_evidence):
    body = post_single(env, name)
    h = body["hallucination"]
    assert h["hallucination_status"] == status
    assert h["hallucination_detected"] == (n_claims > 0)
    assert len(h["claim_evidence"]) == n_claims
    for claim in h["claim_evidence"]:
        assert claim["supported"] is False
        assert claim["reason"].strip()
        assert bool(claim["evidence"]) == claims_have_evidence

    if n_claims == 0:
        assert h["unsupported_claims"] == []               # no false positive on clean answers
    else:
        # hallucination contribution is zeroed: overall = 0.25*rel + 0.30*acc + 0.15*comp
        expected = 0.25 * body["relevance"]["score"] + 0.30 * body["accuracy"]["score"] + 0.15 * body["completeness"]["score"]
        assert body["overall_score"] == pytest.approx(expected, abs=1e-6)
        assert body["verdict"] != "PASS"
    if status == "full":
        assert body["verdict"] == "FAIL"


def test_supported_claim_in_a_mixed_answer_is_not_flagged(env):
    body = post_single(env, "G_mixed")
    assert "Madrid is the capital of Spain" not in body["hallucination"]["unsupported_claims"]
    assert body["hallucination"]["unsupported_claims"] == ["the Ebro river flows through the city"]


@pytest.mark.parametrize("name,category,n_missing,expected_overall,verdict", [
    ("A_correct", "complete", 0, 1.00, "PASS"),                          # fully answered
    ("K_partially_answered", "mostly_complete", 1, 0.91, "PASS"),        # partially answered
    ("D_incomplete", "incomplete", 2, 0.69, "PARTIAL"),
    ("L_substantially_incomplete", "incomplete", 3, 0.62, "PARTIAL"),    # substantially incomplete
])
def test_completeness_cases(env, name, category, n_missing, expected_overall, verdict):
    body = post_single(env, name)
    c = body["completeness"]
    assert c["category"] == category
    assert len(c["missing_aspects"]) == n_missing
    assert c["missing_aspects"] == SCENARIOS[name]["llm"]["completeness"]["missing_aspects"]
    assert c["addressed_aspects"] == SCENARIOS[name]["llm"]["completeness"]["addressed_aspects"]
    assert body["overall_score"] == pytest.approx(expected_overall, abs=1e-6)
    assert body["verdict"] == verdict
    if n_missing:
        assert any("Missing" in issue for issue in body["major_issues"])
        assert any("missing" in s.lower() for s in body["improvement_suggestions"])


def test_missing_aspect_alone_can_still_pass_because_completeness_weighs_15_percent(env):
    """Documents existing model behavior (not a defect): a Pass may still list a missing aspect."""
    body = post_single(env, "K_partially_answered")
    assert body["verdict"] == "PASS"
    assert body["completeness"]["missing_aspects"] == ["most famous train service"]
    assert body["major_issues"], "the missing aspect must still be surfaced to the user"


# ----------------------------------------------------------------------------
# 6. Verdict validation (hand-calculated, existing model & thresholds)
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("rel,acc,hal,comp,detected,status,expected_overall,expected_verdict", [
    (1.0, 1.0, 1.0, 1.0, False, "none", 1.00, "PASS"),
    (0.8, 0.8, 0.8, 0.8, False, "none", 0.80, "PASS"),          # exact Pass boundary
    (0.8, 0.8, 0.8, 0.7, False, "none", 0.785, "PARTIAL"),      # just under the boundary
    (0.5, 0.5, 0.5, 0.5, False, "none", 0.50, "PARTIAL"),       # exact Needs-Improvement boundary
    (0.4, 0.5, 0.5, 0.5, False, "none", 0.475, "FAIL"),         # just under
    (0.0, 0.0, 0.0, 0.0, False, "none", 0.00, "FAIL"),
    (1.0, 1.0, 0.9, 1.0, True, "partial", 0.70, "PARTIAL"),     # detected hallucination contributes 0
    (1.0, 0.9, 0.9, 1.0, True, "full", 0.67, "FAIL"),           # severe override: 0.67 alone would be PARTIAL
    (1.0, 1.0, 1.0, 1.0, True, "full", 0.70, "FAIL"),           # override wins even with perfect other scores
])
def test_verdict_agent_weighted_score_and_thresholds(rel, acc, hal, comp, detected, status, expected_overall, expected_verdict):
    result = VerdictAgent().aggregate(
        JudgeResult(agent_name="relevance", score=rel, reason="r"),
        JudgeResult(agent_name="accuracy", score=acc, reason="a"),
        HallucinationResult(agent_name="hallucination", score=hal, reason="h",
                            hallucination_detected=detected, hallucination_status=status),
        CompletenessResult(agent_name="completeness", score=comp, reason="c"),
    )
    assert result["overall_score"] == pytest.approx(expected_overall, abs=1e-9)
    assert result["verdict"] == expected_verdict
    assert result["verdict_label"] == VERDICT_LABELS[expected_verdict]


# ----------------------------------------------------------------------------
# Agent-output consistency (fault injection: unusual-but-plausible LLM output)
# ----------------------------------------------------------------------------

def test_completeness_category_agrees_with_a_low_score_even_when_no_aspects_are_listed(monkeypatch):
    monkeypatch.setattr(LLMClient, "complete", lambda self, prompt, max_tokens=1000: json.dumps(
        {"score": 0.3, "addressed_aspects": [], "missing_aspects": [], "reason": "Barely answers the question."}))
    result = CompletenessJudgeAgent().evaluate(EvaluationRequest(question="q", ai_response="a"), [])
    assert result.score == 0.3
    assert result.category == "incomplete"     # must not read "complete" next to a 0.3 score


def test_hallucination_status_agrees_with_flagged_claims(monkeypatch):
    monkeypatch.setattr(LLMClient, "complete", lambda self, prompt, max_tokens=1000: json.dumps({
        "score": 0.4, "hallucination_status": "none", "reason": "Inconsistent judge output.",
        "claims": [{"claim": "X is 5", "supported": False, "evidence": [], "reason": "Not in evidence."}]}))
    result = HallucinationDetectionAgent().evaluate(EvaluationRequest(question="q", ai_response="a"), ["e"])
    assert result.hallucination_detected is True
    assert result.hallucination_status != "none"   # a flagged claim can't coexist with status "none"


# ----------------------------------------------------------------------------
# 8. Dashboard validation against a known dataset
# ----------------------------------------------------------------------------

def mk(overall, dim, verdict, detected=False, status="none", missing=None, hal=None):
    hal_score = dim if hal is None else hal
    return EvaluationResult(
        question=f"Known dataset question {verdict} {overall}", ai_response="Known answer.",
        relevance=JudgeResult(agent_name="relevance", score=dim, category="fully_relevant", reason="r"),
        accuracy=JudgeResult(agent_name="accuracy", score=dim, category="correct", reason="a"),
        hallucination=HallucinationResult(
            agent_name="hallucination", score=hal_score, reason="h", hallucination_detected=detected,
            hallucination_status=status,
            unsupported_claims=["bad claim"] if detected else [],
            claim_evidence=[FlaggedClaim(claim="bad claim", supported=False, evidence=["e"], reason="r")] if detected else []),
        completeness=CompletenessResult(agent_name="completeness", score=dim, category="complete", reason="c",
                                        missing_aspects=missing or []),
        overall_score=overall, verdict=verdict, verdict_label=VERDICT_LABELS[verdict],
        major_issues=[], consolidated_summary="s", improvement_suggestions=[])


@pytest.fixture
def known(env):
    """25 records: 10 PASS (batch P), 10 PARTIAL (batch Q), 5 FAIL (single evaluations)."""
    store = env.store
    env.batch_p, env.batch_q = store.new_batch_id(), store.new_batch_id()
    for i in range(10):
        store.save(mk(0.9, 0.9, "PASS"), batch_id=env.batch_p, row_number=i + 1)
    for i in range(10):
        store.save(mk(0.6, 0.6, "PARTIAL"), batch_id=env.batch_q, row_number=i + 1)
    for _ in range(5):
        store.save(mk(0.2, 0.2, "FAIL", detected=True, status="full", missing=["a missing aspect"], hal=0.0))
    return env


KNOWN_STATS = {
    "total_records": 25, "pass_count": 10, "needs_improvement_count": 10, "fail_count": 5,
    "pass_pct": 40.0, "needs_improvement_pct": 40.0, "fail_pct": 20.0,
    "average_relevance": 0.64, "average_accuracy": 0.64, "average_hallucination": 0.60,
    "average_completeness": 0.64, "average_overall": 0.64,
    "hallucination_count": 5, "hallucination_frequency": 0.2,
    "records_with_missing_aspects": 5, "missing_aspects_frequency": 0.2,
    "score_distribution": {"0.0-0.2": 0, "0.2-0.4": 5, "0.4-0.6": 0, "0.6-0.8": 10, "0.8-1.0": 10},
}


def test_dashboard_stats_match_hand_calculation_and_sql_for_known_dataset(known):
    stats = known.client.get("/dashboard/stats").json()
    assert_stats_match(stats, KNOWN_STATS)
    assert {i["issue"]: i["count"] for i in stats["top_issues"]} == {
        "Low relevance": 5, "Low accuracy": 5, "Hallucinated claims": 5, "Incomplete response": 5}
    db = known.store.db_path
    assert sql_one(db, "SELECT COUNT(*) FROM evaluation_results") == stats["total_records"]
    assert sql_one(db, "SELECT AVG(overall_score) FROM evaluation_results") == pytest.approx(stats["average_overall"], abs=1e-4)
    assert sql_one(db, "SELECT AVG(hallucination_score) FROM evaluation_results") == pytest.approx(stats["average_hallucination"], abs=1e-4)
    assert sql_one(db, "SELECT SUM(verdict='FAIL') FROM evaluation_results") == stats["fail_count"]
    assert sql_one(db, "SELECT SUM(missing_aspects_count>0) FROM evaluation_results") == stats["records_with_missing_aspects"]


@pytest.mark.parametrize("params,expected_total,check", [
    ({"verdict": "FAIL"}, 5, lambda r: r["verdict"] == "FAIL"),
    ({"verdict": "PASS"}, 10, lambda r: r["verdict"] == "PASS"),
    ({"min_score": 0.5}, 20, lambda r: r["overall_score"] >= 0.5),
    ({"max_score": 0.3}, 5, lambda r: r["overall_score"] <= 0.3),
    ({"min_score": 0.5, "max_score": 0.7}, 10, lambda r: 0.5 <= r["overall_score"] <= 0.7),
    ({"verdict": "PASS", "min_score": 0.95}, 0, lambda r: True),      # filters that match nothing
    ({"verdict": "BOGUS"}, 0, lambda r: True),
    ({"batch_id": "no-such-batch"}, 0, lambda r: True),
])
def test_dashboard_filters_apply_to_both_statistics_and_records(known, params, expected_total, check):
    stats = known.client.get("/dashboard/stats", params=params).json()
    records = known.client.get("/dashboard/records", params={**params, "limit": 100}).json()["records"]
    assert stats["total_records"] == expected_total
    assert len(records) == expected_total
    assert all(check(r) for r in records)
    if expected_total == 0:
        assert stats["average_overall"] == 0.0 and stats["top_issues"] == []


def test_dashboard_batch_filter_matches_each_batch_and_reset_restores_everything(known):
    for batch_id, verdict in ((known.batch_p, "PASS"), (known.batch_q, "PARTIAL")):
        stats = known.client.get("/dashboard/stats", params={"batch_id": batch_id}).json()
        assert stats["total_records"] == 10
        records = known.client.get("/dashboard/records", params={"batch_id": batch_id, "limit": 100}).json()["records"]
        assert {r["verdict"] for r in records} == {verdict}
    assert known.client.get("/dashboard/stats").json()["total_records"] == 25   # "reset" = no filters
    batches = known.client.get("/dashboard/batches").json()["batches"]
    assert {b["batch_id"]: b["record_count"] for b in batches} == {known.batch_p: 10, known.batch_q: 10}


def test_dashboard_pagination_is_complete_disjoint_and_newest_first(known):
    pages = [known.client.get("/dashboard/records", params={"limit": 10, "offset": off}).json()["records"] for off in (0, 10, 20)]
    assert [len(p) for p in pages] == [10, 10, 5]
    ids = [r["id"] for p in pages for r in p]
    assert len(set(ids)) == 25
    stamps = [r["created_at"] for p in pages for r in p]
    assert stamps == sorted(stamps, reverse=True)
    assert known.client.get("/dashboard/records", params={"limit": 10, "offset": 25}).json()["records"] == []


def test_dashboard_refresh_is_stable_and_reflects_new_data(known):
    first = known.client.get("/dashboard/stats").json()
    assert known.client.get("/dashboard/stats").json() == first
    known.store.save(mk(0.9, 0.9, "PASS"))
    refreshed = known.client.get("/dashboard/stats").json()
    assert refreshed["total_records"] == 26 and refreshed["pass_count"] == 11


def test_dashboard_drill_down_returns_the_stored_result(known):
    for rec in known.client.get("/dashboard/records", params={"limit": 3}).json()["records"]:
        assert known.client.get(f"/dashboard/records/{rec['id']}").json() == known.store.get_record(rec["id"])["full_result"]


def test_large_batch_pdf_contains_first_and_last_record_across_many_pages(env):
    batch_id = env.store.new_batch_id()
    for i in range(1, 61):
        result = mk(0.9, 0.9, "PASS")
        result.question = f"Large batch question number {i}"
        env.store.save(result, batch_id=batch_id, row_number=i)
    resp = env.client.get(f"/reports/batch/{batch_id}/pdf")
    text, pages = pdf_text(resp.content)
    assert resp.status_code == 200 and pages >= 5
    assert "Records included: 60" in text
    assert "Large batch question number 1 AI response:" in text and "Large batch question number 60 AI response:" in text


# ----------------------------------------------------------------------------
# 10. Error handling
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {"question": "", "ai_response": "answer"},
    {"question": "q", "ai_response": ""},
    {"question": "q"},
    {"ai_response": "a"},
    {},
])
def test_single_evaluation_rejects_missing_or_empty_required_fields(env, payload):
    assert env.client.post("/evaluate", json=payload).status_code == 422
    assert env.client.get("/dashboard/stats").json()["total_records"] == 0     # nothing stored


@pytest.mark.parametrize("filename,raw,expected_fragment", [
    ("data.txt", b"question,ai_response\nq,a\n", "csv"),
    ("empty.csv", b"", "empty"),
    ("binary.csv", b"\xff\xfe\x00\x00not utf8", "utf-8"),
    ("cols.csv", b"question,reference_answer\nq,r\n", "ai_response"),
    ("cols2.csv", b"foo,bar\n1,2\n", "question"),
])
def test_batch_upload_rejects_unusable_files_cleanly(env, filename, raw, expected_fragment):
    resp = post_batch(env, raw, filename)
    assert resp.status_code == 400
    assert expected_fragment.lower() in resp.json()["detail"].lower()
    assert env.client.get("/dashboard/stats").json()["total_records"] == 0


def test_batch_with_header_only_completes_with_zero_records(env):
    msgs = ndjson(post_batch(env, b"question,ai_response,reference_answer,source_document\n"))
    init = next(m for m in msgs if m["type"] == "init")
    summary = next(m for m in msgs if m["type"] == "summary")["summary"]
    assert (init["total_records"], init["valid_records"]) == (0, 0)
    assert summary["evaluated_records"] == 0 and summary["average_overall"] == 0.0


def test_batch_of_only_invalid_rows_reports_them_and_stores_nothing(env):
    msgs = ndjson(post_batch(env, csv_bytes([("", "a", "", ""), ("q", "", "", "")])))
    init = next(m for m in msgs if m["type"] == "init")
    assert (init["valid_records"], init["invalid_records"]) == (0, 2)
    assert env.client.get("/dashboard/stats").json()["total_records"] == 0


def test_nonexistent_record_and_batch_return_404(env):
    assert env.client.get("/dashboard/records/does-not-exist").status_code == 404
    assert env.client.get("/reports/batch/does-not-exist/pdf").status_code == 404


def test_empty_dashboard_returns_zeroed_structures_not_errors(env):
    stats = env.client.get("/dashboard/stats").json()
    assert stats["total_records"] == 0 and stats["average_overall"] == 0.0
    assert stats["top_issues"] == [] and sum(stats["score_distribution"].values()) == 0
    assert env.client.get("/dashboard/records").json() == {"records": [], "count": 0}
    assert env.client.get("/dashboard/batches").json() == {"batches": []}


@pytest.mark.parametrize("params", [{"min_score": 1.5}, {"max_score": -0.1}, {"limit": 0}, {"limit": 1001}, {"offset": -1}])
def test_dashboard_rejects_out_of_range_query_parameters(env, params):
    assert env.client.get("/dashboard/records", params=params).status_code == 422


def test_retriever_survives_vector_store_failure_and_keeps_user_source(env):
    class BrokenStore:
        def query(self, *args, **kwargs):
            raise RuntimeError("vector store unavailable")

    retriever = Retriever.__new__(Retriever)
    retriever._store = BrokenStore()
    assert env.real_retrieve(retriever, "any question", "user provided source") == ["user provided source"]
    assert env.real_retrieve(retriever, "any question") == []


def test_pdf_for_records_with_special_characters_and_long_text(env):
    batch_id = env.store.new_batch_id()
    long_result = mk(0.9, 0.9, "PASS")
    long_result.question = "Why & how <does> this work? " * 30
    long_result.ai_response = "Because <b>reasons</b> & more reasons. " * 80
    env.store.save(long_result, batch_id=batch_id, row_number=1)
    resp = env.client.get(f"/reports/batch/{batch_id}/pdf")
    text, pages = pdf_text(resp.content)
    assert resp.status_code == 200 and pages >= 2
    assert "Because <b>reasons</b> & more reasons." in text


# ----------------------------------------------------------------------------
# Known defects - documented with strict xfail so a fix is noticed immediately
# ----------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason=(
    "KNOWN DEFECT D-1: if the LLM is unavailable, every agent falls back to score 0.0, so the "
    "evaluation 'succeeds' as a FAIL verdict and is persisted/counted as a genuine result. "
    "Needs a design decision (raise vs. mark as errored). See docs/evaluation/milestone4_testing.md."))
def test_total_llm_outage_is_not_stored_as_a_genuine_fail_verdict(env):
    env.llm.fail_for.add("A_correct")
    resp = env.client.post("/evaluate", json=payload_for("A_correct"))
    stored = env.client.get("/dashboard/stats").json()["total_records"]
    assert resp.status_code >= 500 or stored == 0


@pytest.mark.xfail(strict=True, reason=(
    "KNOWN DEFECT D-5 (low): a whitespace-only question passes schema validation (min_length=1 "
    "counts spaces). The web UI trims input, but direct API callers can submit it."))
def test_whitespace_only_question_is_rejected(env):
    assert env.client.post("/evaluate", json={"question": "   ", "ai_response": "answer"}).status_code == 422
