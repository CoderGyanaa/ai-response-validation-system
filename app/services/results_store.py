"""
Persists every evaluation result (single and batch) so the M4.1 dashboard
and M4.2 PDF export can be generated from real stored data, not manually
entered numbers, per the Milestone 4 requirement.

Uses SQLite via the Python standard library — no new dependency, consistent
with the project's "avoid unnecessary dependencies" rule. The full
EvaluationResult is stored as JSON for drill-down; individual scores are
also stored as columns so SQL can filter/aggregate without deserializing
every row.
"""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config.settings import settings
from app.models.schemas import EvaluationResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_results (
    id TEXT PRIMARY KEY,
    batch_id TEXT,
    row_number INTEGER,
    created_at TEXT NOT NULL,
    question TEXT NOT NULL,
    ai_response TEXT NOT NULL,
    relevance_score REAL NOT NULL,
    accuracy_score REAL NOT NULL,
    hallucination_score REAL NOT NULL,
    hallucination_detected INTEGER NOT NULL,
    hallucination_status TEXT NOT NULL,
    completeness_score REAL NOT NULL,
    missing_aspects_count INTEGER NOT NULL,
    overall_score REAL NOT NULL,
    verdict TEXT NOT NULL,
    verdict_label TEXT NOT NULL,
    full_result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_batch_id ON evaluation_results(batch_id);
CREATE INDEX IF NOT EXISTS idx_verdict ON evaluation_results(verdict);
CREATE INDEX IF NOT EXISTS idx_created_at ON evaluation_results(created_at);
"""


class ResultsStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or settings.RESULTS_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save(self, result: EvaluationResult, batch_id: Optional[str] = None, row_number: Optional[int] = None) -> str:
        record_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_results (
                    id, batch_id, row_number, created_at, question, ai_response,
                    relevance_score, accuracy_score, hallucination_score,
                    hallucination_detected, hallucination_status,
                    completeness_score, missing_aspects_count,
                    overall_score, verdict, verdict_label, full_result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id, batch_id, row_number,
                    datetime.now(timezone.utc).isoformat(),
                    result.question, result.ai_response,
                    result.relevance.score, result.accuracy.score, result.hallucination.score,
                    int(result.hallucination.hallucination_detected), result.hallucination.hallucination_status,
                    result.completeness.score, len(result.completeness.missing_aspects),
                    result.overall_score, result.verdict, result.verdict_label,
                    result.model_dump_json(),
                ),
            )
        return record_id

    def new_batch_id(self) -> str:
        return str(uuid.uuid4())

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["full_result"] = json.loads(d.pop("full_result_json"))
        d["hallucination_detected"] = bool(d["hallucination_detected"])
        return d

    def get_record(self, record_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evaluation_results WHERE id = ?", (record_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_records(
        self,
        verdict: Optional[str] = None,
        batch_id: Optional[str] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        query = "SELECT * FROM evaluation_results WHERE 1=1"
        params: list = []
        if verdict:
            query += " AND verdict = ?"
            params.append(verdict)
        if batch_id:
            query += " AND batch_id = ?"
            params.append(batch_id)
        if min_score is not None:
            query += " AND overall_score >= ?"
            params.append(min_score)
        if max_score is not None:
            query += " AND overall_score <= ?"
            params.append(max_score)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_batches(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT batch_id, COUNT(*) as record_count, MIN(created_at) as started_at, MAX(created_at) as finished_at
                FROM evaluation_results
                WHERE batch_id IS NOT NULL
                GROUP BY batch_id
                ORDER BY started_at DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def compute_stats(
        self,
        verdict: Optional[str] = None,
        batch_id: Optional[str] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
    ) -> dict:
        """Aggregate stats over stored records, matching the filters a caller applies."""
        records = self.list_records(
            verdict=verdict, batch_id=batch_id, min_score=min_score, max_score=max_score, limit=100000,
        )
        n = len(records)
        if n == 0:
            return {
                "total_records": 0, "pass_count": 0, "needs_improvement_count": 0, "fail_count": 0,
                "pass_pct": 0.0, "needs_improvement_pct": 0.0, "fail_pct": 0.0,
                "average_relevance": 0.0, "average_accuracy": 0.0,
                "average_hallucination": 0.0, "average_completeness": 0.0, "average_overall": 0.0,
                "hallucination_count": 0, "hallucination_frequency": 0.0,
                "records_with_missing_aspects": 0, "missing_aspects_frequency": 0.0,
                "score_distribution": {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0},
                "top_issues": [],
            }

        pass_count = sum(1 for r in records if r["verdict"] == "PASS")
        partial_count = sum(1 for r in records if r["verdict"] == "PARTIAL")
        fail_count = sum(1 for r in records if r["verdict"] == "FAIL")
        hallucination_count = sum(1 for r in records if r["hallucination_detected"])
        missing_count = sum(1 for r in records if r["missing_aspects_count"] > 0)

        buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
        for r in records:
            s = r["overall_score"]
            if s < 0.2:
                buckets["0.0-0.2"] += 1
            elif s < 0.4:
                buckets["0.2-0.4"] += 1
            elif s < 0.6:
                buckets["0.4-0.6"] += 1
            elif s < 0.8:
                buckets["0.6-0.8"] += 1
            else:
                buckets["0.8-1.0"] += 1

        issue_counts: dict[str, int] = {}
        for r in records:
            if r["relevance_score"] < 0.5:
                issue_counts["Low relevance"] = issue_counts.get("Low relevance", 0) + 1
            if r["accuracy_score"] < 0.5:
                issue_counts["Low accuracy"] = issue_counts.get("Low accuracy", 0) + 1
            if r["hallucination_detected"]:
                issue_counts["Hallucinated claims"] = issue_counts.get("Hallucinated claims", 0) + 1
            if r["missing_aspects_count"] > 0:
                issue_counts["Incomplete response"] = issue_counts.get("Incomplete response", 0) + 1
        top_issues = sorted(
            [{"issue": k, "count": v} for k, v in issue_counts.items()],
            key=lambda x: -x["count"],
        )

        return {
            "total_records": n,
            "pass_count": pass_count,
            "needs_improvement_count": partial_count,
            "fail_count": fail_count,
            "pass_pct": round(100 * pass_count / n, 1),
            "needs_improvement_pct": round(100 * partial_count / n, 1),
            "fail_pct": round(100 * fail_count / n, 1),
            "average_relevance": round(sum(r["relevance_score"] for r in records) / n, 4),
            "average_accuracy": round(sum(r["accuracy_score"] for r in records) / n, 4),
            "average_hallucination": round(sum(r["hallucination_score"] for r in records) / n, 4),
            "average_completeness": round(sum(r["completeness_score"] for r in records) / n, 4),
            "average_overall": round(sum(r["overall_score"] for r in records) / n, 4),
            "hallucination_count": hallucination_count,
            "hallucination_frequency": round(hallucination_count / n, 4),
            "records_with_missing_aspects": missing_count,
            "missing_aspects_frequency": round(missing_count / n, 4),
            "score_distribution": buckets,
            "top_issues": top_issues,
        }
