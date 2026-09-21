# Milestone 3 — Completeness, Verdict, Results Display & Batch Evaluation

## M3.1 — Completeness Judge Agent

Extends the original score-only Completeness agent (see `docs/evaluation/evaluation.md`) to break the question into its individual sub-requirements and report which ones the response actually addresses.

**Input:** question, AI response, reference answer (if provided), retrieved evidence
**Output** (`CompletenessResult`, extends `JudgeResult`):
- `score` — 1.0 (all requirements addressed) down to 0.0–0.3 (most requirements missing)
- `addressed_aspects` — list of sub-requirements the response covers
- `missing_aspects` — list of sub-requirements the response omits or under-covers
- `category` — derived as `complete` / `mostly_complete` / `incomplete`
- `reason` — one-sentence explanation

When a reference answer is available it's used to identify what should be covered; otherwise retrieved evidence is used. Implemented in `app/agents/completeness.py`.

## M3.2 — Verdict Agent & Weighted Evaluation

The Verdict agent (`app/agents/verdict.py`) combines all four judge outputs into a single evaluation result.

**Weighted scoring model** (unchanged from M2, carried forward): Accuracy 30%, Hallucination 30%, Relevance 25%, Completeness 15%. Accuracy and Hallucination are weighted highest since factual correctness matters most; a detected hallucination's score contribution is zeroed regardless of its raw score.

**Verdict thresholds:**
- `overall_score ≥ 0.80` → **Pass**
- `0.50 ≤ overall_score < 0.80` → **Needs Improvement**
- `overall_score < 0.50` → **Fail**

**Severe hallucination override:** if `hallucination_status == "full"`, the verdict is forced to **Fail** regardless of the weighted average. This ensures a fabricated, fully-contradicted answer can't be masked by otherwise-good relevance/accuracy/completeness scores.

**Output additions:**
- `verdict_label` — the spec-facing wording ("Pass" / "Needs Improvement" / "Fail"), alongside the existing internal `verdict` (`PASS`/`PARTIAL`/`FAIL`) kept for backward compatibility with earlier tests and API consumers
- `major_issues` — a list of the most significant problems found (hallucinated claims, low accuracy, missing aspects, low relevance)
- `consolidated_summary` — a one-paragraph synthesis combining the overall score, verdict, and major issues

## M3.3 — Per-Dimension Scoring & Evaluation Results Display

The frontend (`app/static/index.html`) presents every field the backend returns, organized as:

1. **Hero verdict card** — Pass/Needs Improvement/Fail, weighted overall score, `consolidated_summary`, and an "evidence-backed evaluation" indicator (derived from whether the Accuracy or Hallucination agents' evidence arrays are non-empty)
2. **Score overview** — a four-card grid (Relevance, Accuracy, Hallucination, Completeness) with score, category/status badge, and a ring indicator
3. **Pipeline visualization** — a static diagram showing Question + Response → RAG Evidence → four judges → Weighted Verdict, so a reviewer can see how the result was produced
4. **"Why this verdict?"** — strengths (from high-scoring judges' own reasoning), warnings and critical issues (derived from `major_issues`)
5. **Detailed judge panels** (collapsible) — Relevance, Accuracy (with a claim → evidence → reasoning flow), Hallucination Investigation (claim-level cards distinguishing contradicted vs. unsupported claims, or a "No unsupported claims detected" success state), and Completeness (addressed vs. missing aspects)
6. **Evidence explorer** — retrieved evidence shown as source cards
7. **Response vs. evidence comparison** — the AI response (with flagged claims underlined) alongside the retrieved evidence
8. **Score interpretation guide** — the same thresholds used by the Verdict agent, shown for reference

All of the above is rendered strictly from fields the API already returns — no fabricated timestamps, similarity scores, or source metadata.

## M3.4 — Batch Evaluation Module

Allows evaluating many question/response pairs at once from a single CSV upload, without duplicating any evaluation logic — every valid row is run through the same `EvaluationOrchestrator` used by the single-evaluation endpoint.

### CSV format

The system accepts an externally created CSV file through the frontend's upload interface (a plain file picker — no dependency on any particular spreadsheet tool).

| Column | Required | Notes |
|---|---|---|
| `question` | Yes | Must be non-empty |
| `ai_response` | Yes | Must be non-empty |
| `reference_answer` | No | Blank is treated as "not provided" |
| `source_document` | No | Blank is treated as "not provided" |

Column names are matched case-insensitively. A header row is required.

### Validation and error handling

- **File-level rejection** (whole upload refused, no rows processed): file isn't a `.csv`, file is empty, file isn't valid UTF-8 text, or a required column is missing from the header entirely.
- **Row-level rejection** (that row is skipped, the rest of the batch continues): a required field (`question` or `ai_response`) is blank or missing on that row. Each invalid row is reported with its row number and the specific reason (e.g. "Missing required field(s): ai_response").
- A fully blank line (e.g. a trailing newline at the end of the file) is skipped silently and not counted as an error.
- If evaluation itself fails for a row that passed CSV validation (an unexpected exception from the orchestrator), that row is recorded with an error message rather than stopping the remaining rows.

### Processing and progress

The batch endpoint (`POST /evaluate/batch`, in its own router separate from `/evaluate`) streams newline-delimited JSON (NDJSON) as each row actually completes, so the frontend's progress counter reflects real, incremental completions rather than a simulated progress bar.

### Results display

- A results table lists every processed row: row number, question, per-dimension scores, hallucination status, overall score, and final verdict.
- Each row has a "View" action that opens the same detailed evaluation view built for M3.3 — no separate rendering logic was written for batch records.
- An aggregate statistics panel shows: total/valid/invalid record counts, evaluated/failed counts, average score per dimension, Pass/Needs Improvement/Fail counts, and hallucination frequency (the fraction of evaluated records where a hallucination was detected).

### Testing and validation

Automated coverage (`tests/test_batch.py`, 13 tests): CSV parsing (valid multi-row file, missing required column, empty required field, malformed/short row, optional fields left blank, one invalid row not blocking others), batch service behavior (all valid rows evaluated, one row's evaluation failure not stopping the batch, aggregate statistics computed correctly including the zero-records edge case), and the streaming API endpoint (rejects non-CSV files, rejects a missing required column, and a full mixed valid/invalid batch produces the correct init/progress/summary messages).

Manual end-to-end verification: a 5-row CSV (4 valid, 1 with a missing `ai_response`) was uploaded through the frontend. The invalid row was correctly reported ("Row 5: Missing required field(s): ai_response") without stopping the batch; all 4 valid rows were evaluated (observed outcomes: a correct Paris answer → Pass, an incorrect Berlin answer → Fail, a partially complete primary-colors answer → Needs Improvement, and a partially correct Eiffel Tower answer → Needs Improvement); aggregate statistics and the per-row results table displayed correctly; the "View" buttons correctly opened the detailed result for each record.
