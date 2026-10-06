# Milestone 4.3 — End-to-End Testing & System Validation

Test file: `tests/test_e2e.py` (87 tests) plus support code in `tests/e2e_support.py`.
Consistency check script: `scripts/run_consistency_check.py` (manual, needs a live API key).

## Method and its honest limits

Every test here runs the *real* orchestrator, all four *real* agents, the *real*
Verdict Agent, the *real* SQLite results store, the *real* FastAPI routes,
dashboard endpoints, and PDF generator. Two things are replaced:

- **`LLMClient.complete`** → `FakeLLM`, which returns a scripted JSON judge
  response for each scenario, so every run is deterministic and free.
- **`Retriever.retrieve`** → `FakeRetrieval`, which returns each scenario's
  fixed evidence list instead of querying a live vector store.

**What this proves:** pipeline wiring, weighted-score math, verdict
thresholds, the severe-hallucination override, evidence/claims/aspects
preservation end to end, batch isolation of invalid rows, SQLite persistence,
dashboard aggregation correctness (checked against independent raw-SQL
queries, not just the same code path twice), and PDF/dashboard/database
agreement.

**What this does NOT prove:** whether Gemini's actual judgments are *good*.
That is a separate question, already covered by `scripts/run_validation_suite.py`
(M2.4, real Gemini, 22/22 outcomes matched at last run) and now also by
`scripts/run_consistency_check.py` for repeat-run stability (below). One test,
`test_end_to_end_with_real_vector_store_retrieval`, uses a real ChromaDB +
sentence-transformers instance (still a scripted LLM) to check the real RAG
path specifically; it is skipped automatically where those packages aren't
installed and should be run on a machine that has them.

## 1–2. Single and batch end-to-end

12 scenarios (A–L, V, Z) covering: fully correct, incorrect, partially
correct, incomplete, off-topic, unsupported/hallucinated, mixed
supported+unsupported claims, no-reference-answer (RAG-only), a vague
non-answer, a substantially incomplete answer, and special characters
(`&`, `<`, `>`) in the question and response.

Each scenario's expected weighted score is a hand-calculated literal in
`e2e_support.py`, checked two ways: against that literal, and against an
independently recomputed formula (`independent_weighted`) so a bug that
happened to match one derivation wouldn't be missed by relying on only one.

For each scenario, `test_single_evaluation_end_to_end` verifies: all four
scores are in `[0, 1]`, all four categories/status are on the documented
list, every reason is non-empty, evidence/claims/aspects survive from the
scripted judge output through to the stored and API-returned result
unchanged, the weighted score and verdict match, the record is persisted
with `batch_id = null`, and drill-down (`/dashboard/records/{id}`) returns
byte-for-byte what `/evaluate` returned.

Batch coverage: an 11-row CSV with 8 valid rows (one per scenario A–D, F, G,
E, Z) and 3 invalid rows (empty question, empty response, a malformed row
with too few columns). Verified: invalid rows never reach evaluation and are
reported with the correct row number and reason; the batch streams `init` →
8×`progress` → `summary` with correct running counts; a shared `batch_id`
links all 8 persisted rows and nothing is stored for the 3 invalid ones;
`/dashboard/stats?batch_id=...` matches both a hand-calculated expectation
table and independent raw SQL aggregates against the same database file;
`top_issues` counts and ordering are correct; every record's dashboard
drill-down equals what was streamed during the batch; two separate batches
stay isolated from each other but correctly combine in the unfiltered
dashboard view; and injecting a real orchestrator failure on one row (via
`monkeypatch`, not the fake LLM) leaves the other rows unaffected and is
reflected in `failed_records`.

## 3–6. Agent scoring, hallucination, completeness, verdict validation

Parametrized directly over the scenario table (no separate fixtures to keep
in sync). Hallucination cases specifically probe: completely supported
(status `none`, zero flagged claims — checked for false positives),
completely unsupported, mixed supported+unsupported (the supported claim is
asserted to be **absent** from the flagged list), and direct contradiction
with retrieved evidence (status `full`, verdict forced to `FAIL`).
Completeness cases probe fully/partially/substantially-incomplete answers
and check `addressed_aspects`/`missing_aspects` pass through unchanged.

Verdict validation includes the exact 0.8 and 0.5 threshold boundaries (see
defect D-2 below), a just-under-boundary case on each side, and three
variations on the severe-hallucination override, including one where the
other three dimensions are all a perfect 1.0 yet the verdict is still
forced to `FAIL`.

Two additional tests feed a self-contradictory (but individually
well-formed) LLM response directly to `CompletenessJudgeAgent` and
`HallucinationDetectionAgent` respectively, to check the agents don't
propagate a contradiction between a judge's score and its own category/status.
These caught defects D-3 and D-4 (below).

## 7. Scoring consistency

Automated tests can't meaningfully assess "is the LLM consistent with
itself" — that requires the real model. `scripts/run_consistency_check.py`
runs one fixed question/response pair through the real orchestrator N times
(default 5) and reports the score range per dimension, the set of
categories/statuses observed, and whether the **verdict** itself ever
flipped (flagged separately from ordinary score/wording variation, per the
instruction not to demand identical reasoning text).

**Status: not yet run.** This needs a live Gemini API key and is rate-limited
(the script defaults to a 6-second delay between calls); it was not run as
part of this pass so as not to consume API quota without an explicit request.
Run it and record the output here before relying on this section for the
final project report.

## 8. Dashboard validation

`known` fixture seeds a hand-designed 25-record dataset (10 `PASS` in batch
P, 10 `PARTIAL` in batch Q, 5 `FAIL` singles with a hallucination and a
missing aspect each) with pre-calculated expected stats
(`KNOWN_STATS`/`EXPECTED_TOP_ISSUES`). `/dashboard/stats` is checked against
that table, against raw SQL aggregates on the same database file, and its
`top_issues` dict.

Also tested: verdict filter, min/max score filter (including a combined
range and two filters that legitimately match zero records, which must
return zeroed structures rather than an error), a bogus verdict value and a
nonexistent `batch_id` (both correctly return 0 records rather than
erroring), per-batch filtering, "reset" (no filters returns all 25),
pagination (three pages of 10/10/5, all 25 IDs present exactly once, newest
first, and requesting past the end returns empty rather than erroring), and
that a fresh save is immediately visible on the next stats call ("refresh").
Drill-down is checked against the store's own `get_record` for a sample of
records.

## 9. PDF validation

`test_batch_pdf_matches_dashboard_and_stored_records` builds the 8-valid-row
batch, then extracts the PDF's text with `pdfplumber` and checks, line by
line: the batch ID and record count in the header, every summary-table
figure against the live `/dashboard/stats` response for that same batch
(not against a second hand-calculation — so a change to the report template
that silently drifted from the dashboard would be caught), every
recommendation's issue/count/total phrasing against `top_issues`, and the
exact count of `"Verdict: Pass/Needs Improvement/Fail"` occurrences against
the dashboard's verdict counts. Per scenario it also checks the question,
response, accuracy evidence, every flagged claim with its evidence and
reason, and every missing aspect actually appear in the extracted text — and
that the two invalid rows' text never appears in the report at all.

Also covered: a batch where one row failed evaluation (the PDF's "Records
included" count reflects only the 2 that actually succeeded, not the 3
attempted); a 60-record batch spanning 5+ pages with both the first and last
record's text present (nothing silently dropped); and a record with `&`,
`<`, `<b>` and long repeated text, confirming it renders as literal text
across multiple pages rather than crashing or corrupting the markup parser.

## 10. Error handling

Empty/missing `question` or `ai_response` (422, nothing persisted); a `.txt`
upload, an empty file, a non-UTF-8 file, and two different missing-column
CSVs (all 400 with a message naming the actual problem); a CSV with only a
header row (completes normally with zero records rather than erroring); a
CSV of only invalid rows (reported, nothing stored); a nonexistent record ID
and a nonexistent batch ID (404 in both the dashboard and PDF endpoints); an
empty dashboard (zeroed structures, not an error); out-of-range dashboard
query parameters (`min_score=1.5`, negative `offset`, `limit=0` or `1001` —
422 rather than silently clamping or crashing); a vector-store query failure
inside `Retriever` (falls back to the user-supplied source document, or an
empty list, rather than raising into the caller — this is the real
`Retriever.retrieve`, not the fake).

## 11. Performance / bottleneck observations

Not a load test — small numbers, observed rather than optimized:

- **Sequential LLM calls per record.** Each evaluation makes 4 judge calls
  one after another (not concurrently), so wall-clock time for a batch
  scales roughly linearly with row count × 4 × per-call latency. This is the
  dominant cost for real (non-scripted) runs; `run_validation_suite.py`
  already works around this for its own use case with a configurable
  inter-call delay for rate-limit compliance, but batch evaluation itself
  has no concurrency.
- **Batch history endpoint** (`/dashboard/batches` as rendered by the
  frontend) issues one `/dashboard/stats?batch_id=...` call per batch to
  populate the history table. Fine at the scale exercised here (a handful of
  batches); would not scale well to hundreds of batches without a dedicated
  aggregate query.
- **PDF generation** builds the whole document in memory before returning
  it; the 60-record test above completed quickly with no special handling
  needed, but this hasn't been exercised at, say, thousands of records.
- **`ResultsStore.compute_stats`** loads all matching rows into Python and
  aggregates them there rather than using SQL `AVG`/`COUNT` — the E2E tests
  independently verify its output against raw SQL specifically so this
  implementation choice is caught if it ever disagrees, but it does mean
  memory scales with result-set size for very large filters.

None of the above caused a test failure or timeout at the scale tested; they
are flagged as forward-looking limitations, not defects, per the instruction
not to prematurely optimize.

## Defects discovered and fixed

| ID | Where | Symptom | Fix |
|---|---|---|---|
| D-2 | `app/agents/verdict.py` | Floating-point summation could land an exact-boundary input (e.g. all four dimensions at 0.80) on `0.7999999999999999`, misclassifying a `PASS` as `PARTIAL`. | Threshold comparison now uses the score rounded to 6 decimals; the score value returned to callers is unchanged. |
| D-3 | `app/agents/completeness.py` | `category` was derived only from whether `missing_aspects` was empty, so a low score (e.g. `0.3`) with an empty missing-aspects list was labeled `"complete"`. | `category` is now derived from the score first (`≥0.8` and no missing → `complete`; `≥0.5` → `mostly_complete`; else `incomplete`), matching the documented score-band derivation in `docs/evaluation/milestone3.md`. |
| D-4 | `app/agents/hallucination.py` | The status/claims consistency check only fired when the judge returned an unrecognized status string; a *valid* but self-contradictory status (e.g. `"none"` alongside a non-empty flagged-claims list) was passed through unchanged. | The check now runs against the actual filtered claim count regardless of whether the status string itself was recognized, in both directions (claims-but-`none`, and no-claims-but-`partial`/`full`). |

All three were caught by tests written for M4.3 before any production code
was touched; each has a regression test, and the full suite was re-run after
each fix.

## Defects documented but not fixed (open, by design)

| ID | Where | Symptom | Why not fixed now |
|---|---|---|---|
| D-1 | `app/agents/*.py` (shared fallback pattern) | If the LLM is completely unavailable, every judge agent independently falls back to `score=0.0` with a "internal error" reason. The orchestrator has no way to distinguish "the AI response is genuinely terrible" from "the evaluator itself failed," so a total outage is stored and counted as a real `FAIL` verdict rather than surfaced as an evaluation error. | This is a design decision (should a total-failure evaluation be stored at all? Flagged separately? Retried?), not a one-line bug fix, and changing it touches every agent's error-handling contract. Documented via a `strict=True` `xfail` test so it will be visibly noticed the moment someone changes this behavior. |
| D-5 | `app/models/schemas.py` (`EvaluationRequest`) | A whitespace-only `question` (e.g. `"   "`) passes Pydantic's `min_length=1` validation, since spaces count as characters. | Low severity — the web UI already trims input before submitting. Left open and documented via `xfail` rather than changed, since the instruction was to prefer test-only changes and fix only defects actually blocking correctness; this one doesn't. |

## Test counts

**Verified on Gyana's machine** (full dependencies installed, including
`chromadb`/`sentence-transformers`), after the `Retriever` regression fix
described above:

| | Count |
|---|---|
| Tests before M4.3 | 55 |
| New M4.3 tests (`tests/test_e2e.py`) | 87 |
| Total tests collected | 142 |
| Passed | 140 |
| Failed | 0 |
| xfailed (expected, documented defects) | 2 — D-1, D-5 above |
| Skipped | 0 — `test_end_to_end_with_real_vector_store_retrieval` (real ChromaDB + sentence-transformers) now runs and passes, since this machine has both dependencies installed |

This confirms the real-RAG path (real ChromaDB, real embeddings) works end
to end, not just the scripted-retrieval tests.

In a sandbox/CI environment without `chromadb`/`sentence-transformers`
installed, expect `test_retrieval.py` to fail and
`test_end_to_end_with_real_vector_store_retrieval` to skip instead — both
purely due to the missing dependency, not a code defect.

Run with:
```bash
pytest tests/ -v
```
