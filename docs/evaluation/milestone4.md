# Technical Documentation — AI Response Validation System

Complete reference for every implemented component, current as of Milestone 4.4.
This consolidates and cross-references the per-milestone documents already in
`docs/` (`architecture/architecture.md`, `research/research.md`,
`evaluation/evaluation.md`, `evaluation/milestone3.md`,
`evaluation/milestone4_testing.md`) rather than duplicating them — each
section below says where the fuller treatment lives.

## 1. System Architecture

See [`docs/architecture/architecture.md`](../architecture/architecture.md) and
the visual diagram [`docs/architecture/architecture-diagram.svg`](../architecture/architecture-diagram.svg)
for the full component-by-component breakdown. Current end-to-end flow:

```
Client (browser)
  → FastAPI (app/api/routes.py, batch_routes.py, dashboard_routes.py, report_routes.py)
    → Evaluation Service (app/evaluation/service.py) [single-eval path]
    → Batch Service (app/evaluation/batch_service.py) [batch path, reuses the same orchestrator]
      → Retriever (app/retrieval/retriever.py) → Vector Store (app/services/vector_store.py) → ChromaDB
      → Evaluation Orchestrator (app/agents/orchestrator.py)
        → Relevance / Accuracy / Hallucination / Completeness Judge Agents → Gemini
        → Verdict Agent (app/agents/verdict.py)
      → Results Store (app/services/results_store.py) → SQLite
    → Dashboard (reads Results Store) / PDF Report Generator (reads Results Store)
```

Every result — single or batch — is persisted to the same SQLite store, which
is the single source of truth the dashboard and PDF export both read from.

## 2. Evaluation Input Module

`app/api/routes.py` (`POST /evaluate`) accepts an `EvaluationRequest`:
`question` and `ai_response` (required, non-empty), `reference_answer` and
`source_document` (optional). Validation is Pydantic-based
(`app/models/schemas.py`); malformed or missing required fields return
HTTP 422 automatically. On success the request is run through the
orchestrator and the result is persisted before being returned.

## 3. Reference Knowledge Base & RAG Pipeline

Built by `scripts/ingest_knowledge_base.py`: downloads TruthfulQA and SQuAD
from Hugging Face, cleans and standardizes records, chunks them
sentence-aware (short Q/A pairs kept whole; long contexts split only on
sentence boundaries, never mid-word), embeds each chunk locally with
`all-MiniLM-L6-v2` (`sentence-transformers`), and stores vectors + metadata
(dataset, question, answer, source, chunk/document ID) in a persistent
ChromaDB collection. Full detail in
[`docs/evaluation/milestone3.md`](../evaluation/milestone3.md) (M1.4 section)
and [`docs/research/research.md`](../research/research.md).

## 4. Embeddings & Vector Store

`app/services/vector_store.py` wraps ChromaDB. Embeddings are computed
explicitly via a local `SentenceTransformer` instance and passed to Chroma
directly — this was a deliberate fix (documented in the project's defect
history) to avoid Chroma silently falling back to its own bundled default
embedder on collection reload, which caused timeouts. Both ingestion and
query time use the same embedding function, so stored and query vectors are
always compatible.

## 5. Retriever

`app/retrieval/retriever.py` queries the vector store for the top-k most
similar chunks to a question, and prepends the user-supplied
`source_document` when provided. If the vector store is unavailable or a
query fails, it logs a warning and returns whatever evidence it has (the
user's source document, or an empty list) rather than raising — the
pipeline degrades gracefully instead of failing the whole evaluation.
(This component had a regression during development — see Known Limitations
and `docs/evaluation/milestone4_testing.md` — where it had reverted to an
early placeholder that never queried the store at all; this was found via
the M4.3 end-to-end test suite and fixed.)

## 6. Evaluation Orchestrator

`app/agents/orchestrator.py`. For a single `EvaluationRequest`: retrieves
evidence, runs all four judge agents against it, passes their outputs to the
Verdict Agent, and assembles the final `EvaluationResult`. Used identically
by both the single-evaluation endpoint and the batch service — no evaluation
logic is duplicated anywhere in the codebase.

## 7. Judge Agents

Each agent (`app/agents/relevance.py`, `accuracy.py`, `hallucination.py`,
`completeness.py`) prompts Gemini (via `app/services/llm_client.py`) for a
structured JSON verdict, parses it (`app/agents/prompt_utils.py` handles
markdown-fenced JSON and other formatting quirks), and fails gracefully to a
safe default (`score=0.0`, an explanatory reason) if the call or parsing
fails — one agent's failure never crashes the whole evaluation. Full prompt
design and scoring-scale rationale: [`docs/evaluation/evaluation.md`](../evaluation/evaluation.md)
(M2) and [`docs/evaluation/milestone3.md`](../evaluation/milestone3.md) (M3.1).

| Agent | Scores | Categories / Status | Extra output |
|---|---|---|---|
| Relevance | 0.0–1.0 | `fully_relevant`, `partially_relevant`, `unrelated`, `off_topic` | — |
| Accuracy | 0.0–1.0 | `correct`, `partially_correct`, `incorrect`, `contradictory` | `evidence` (list) |
| Hallucination | 0.0–1.0 | status: `none`, `partial`, `full` | `claim_evidence` — each flagged claim's text, whether supported, contradicting evidence, and a reason |
| Completeness | 0.0–1.0 | `complete`, `mostly_complete`, `incomplete` | `addressed_aspects`, `missing_aspects` |

**Hallucination/Completeness category consistency:** both agents
cross-validate the judge's own category/status against its other structured
output (e.g. a `"none"` hallucination status alongside a non-empty flagged
claim, or a `"complete"` label alongside a low score) and resolve the
contradiction from the more concrete signal, rather than trusting a
self-contradictory judge response verbatim. This was added after the M4.3
end-to-end tests surfaced two such defects — see Known Limitations.

## 8. Verdict Agent

`app/agents/verdict.py`. Weighted model:

| Dimension | Weight |
|---|---|
| Accuracy | 0.30 |
| Hallucination | 0.30 |
| Relevance | 0.25 |
| Completeness | 0.15 |

A detected hallucination's contribution to the weighted sum is **zeroed**
(not its raw score) — an unsupported claim should drag the score down, not
be softened by a moderate numeric score. Thresholds:

- `overall_score ≥ 0.80` → **Pass**
- `0.50 ≤ overall_score < 0.80` → **Needs Improvement**
- `overall_score < 0.50` → **Fail**

**Severe-hallucination override:** if `hallucination_status == "full"`, the
verdict is forced to **Fail** regardless of the weighted average — a fully
fabricated/contradicted answer can't be rescued by good scores elsewhere.

**Threshold rounding:** the comparison against 0.80/0.50 uses the score
rounded to 6 decimal places, not the raw floating-point sum — floating-point
summation could otherwise misclassify an exact-boundary input (e.g. all four
dimensions at exactly 0.80) as just under the threshold. The score value
returned to callers and stored is unaffected; only the classification
comparison is rounded.

Output includes `verdict` (internal: `PASS`/`PARTIAL`/`FAIL`, kept for
backward compatibility), `verdict_label` (spec wording: `Pass`/`Needs
Improvement`/`Fail`), `major_issues` (list of significant problems found),
and `consolidated_summary` (one-paragraph synthesis).

## 9. SQLite Results Store

`app/services/results_store.py`. Every evaluation — single or batch — is
persisted with: a UUID, an optional `batch_id` (null for single
evaluations), `row_number` (for batch rows), a timestamp, the question and
response, all four dimension scores plus hallucination status and missing-
aspect count as queryable columns, and the full `EvaluationResult` as JSON
for drill-down. Provides filtered listing (`list_records`), batch summaries
(`list_batches`), and aggregate statistics (`compute_stats` — pass/fail
counts and percentages, per-dimension averages, hallucination and
incomplete-response frequency, a 5-bucket score distribution, and the
top recurring issues found across the filtered set). No value here is
manually entered — every number is computed from the stored rows.

## 10. Dashboard

`app/api/dashboard_routes.py` (API) + the "Dashboard" view in
`app/static/index.html` (UI). Reads exclusively from the Results Store.

**Endpoints:** `GET /dashboard/stats`, `GET /dashboard/records`,
`GET /dashboard/records/{id}`, `GET /dashboard/batches` — all support
`verdict`, `batch_id`, `min_score`, `max_score` filters where applicable
(`/dashboard/records` additionally supports `limit`/`offset` pagination).

**UI sections:** KPI cards, five quality-score rings, a verdict donut chart,
a score-distribution bar chart, hallucination and completeness intelligence
panels, a top-issues list, a batch-history table (each batch's Pass/Needs
Improvement/Fail/average score is fetched live via `/dashboard/stats
?batch_id=...` — not pre-computed or fabricated), a filter bar wired to the
real API, a paginated records table, and drill-down that reuses the exact
same detailed result view built for single evaluations (no duplicated
rendering logic). All charts are hand-built inline SVG — no charting library
was added.

## 11. PDF Report Generation

`app/services/report_generator.py` + `app/api/report_routes.py`
(`GET /reports/batch/{batch_id}/pdf`). Built with reportlab's Platypus
flowables (`Paragraph`, `Table`, `ListFlowable`) rather than manual canvas
coordinates, so long reasoning/evidence text wraps and paginates
automatically instead of overlapping. Reads from the same Results Store as
the dashboard, so the two are always consistent. All user/LLM-generated text
is XML-escaped before insertion, since reportlab parses a markup subset and
unescaped `&`/`<`/`>` would otherwise corrupt or crash generation — this was
caught and fixed during M4.2 development.

**Report contents:** metadata (batch ID, generation timestamp, record
count), a batch summary table (record counts, verdict breakdown, all five
average scores, hallucination and incomplete-response frequency),
improvement recommendations derived from the same `top_issues` data the
dashboard shows (not a separate analysis), and a full per-record section for
every stored row: question, response, per-dimension scores/categories,
reasoning, accuracy evidence, flagged hallucination claims with their
evidence and reasoning, completeness addressed/missing aspects, and the
consolidated summary.

## 12. Batch (CSV) Evaluation Workflow

`app/evaluation/csv_parser.py` + `app/evaluation/batch_service.py` +
`app/api/batch_routes.py` (`POST /evaluate/batch`).

**CSV format:** columns `question`, `ai_response` (required, case-insensitive
header match), `reference_answer`, `source_document` (optional, blank
allowed). A header missing a required column rejects the whole file (400,
naming the missing column); a row with a blank required field is reported
individually (row number + reason) without stopping the rest of the batch.

**Processing:** every valid row is run through the exact same
`EvaluationOrchestrator` used by `/evaluate` — no separate evaluation logic.
Progress is streamed as newline-delimited JSON (`init` → one `progress`
message per completed row → `summary`) so the frontend shows real,
incremental progress rather than a simulated bar. A row that fails
evaluation after passing CSV validation is recorded with an error and does
not stop the remaining rows. All successfully evaluated rows share one
`batch_id`, used to group them in the dashboard and PDF report.

## 13. Data Models

Core schemas in `app/models/schemas.py`: `EvaluationRequest`, `JudgeResult`
(score/category/reason/evidence), `HallucinationResult` (extends
`JudgeResult` with `hallucination_detected`, `hallucination_status`,
`unsupported_claims`, `claim_evidence: List[FlaggedClaim]`),
`CompletenessResult` (extends `JudgeResult` with `addressed_aspects`,
`missing_aspects`), and `EvaluationResult` (the full assembled output,
including `verdict`, `verdict_label`, `major_issues`,
`consolidated_summary`). Batch-specific schemas (`BatchRowError`,
`BatchRecord`, `BatchSummary`) live separately in
`app/models/batch_schemas.py` so the core schemas file is never touched by
the batch feature.

## 14. API Endpoints (complete list)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/evaluate` | Single evaluation; persists the result |
| POST | `/evaluate/batch` | Batch evaluation from an uploaded CSV; streams NDJSON progress |
| GET | `/dashboard/stats` | Aggregate statistics, filterable |
| GET | `/dashboard/records` | Paginated, filterable record summaries |
| GET | `/dashboard/records/{id}` | Full stored result for one record |
| GET | `/dashboard/batches` | List of past batch runs |
| GET | `/reports/batch/{batch_id}/pdf` | Streams the generated PDF report for a batch |

## 15. Scoring Dimensions, Weighted Model, Verdict Thresholds

Covered fully in sections 7–8 above and in
[`docs/evaluation/evaluation.md`](../evaluation/evaluation.md) /
[`docs/evaluation/milestone3.md`](../evaluation/milestone3.md).

## 16. Testing Methodology

Full detail in [`docs/evaluation/milestone4_testing.md`](../evaluation/milestone4_testing.md).
Summary: 142 tests across `tests/test_api.py`, `test_agents.py`,
`test_retrieval.py`, `test_batch.py`, `test_dashboard.py`, `test_report.py`,
and `test_e2e.py` (87 end-to-end tests covering single and batch flows
across 12 representative scenarios, hallucination and completeness edge
cases, verdict threshold/override behavior, dashboard statistics validated
against both hand-calculated expectations and independent raw SQL queries,
PDF content validated against the live dashboard API, and error handling).
End-to-end tests run the real orchestrator/agents/store/API/dashboard/PDF
pipeline with only the Gemini call and vector-store query replaced by
scripted equivalents, plus one test using a real ChromaDB + embedding
instance. `scripts/run_validation_suite.py` (M2.4) and
`scripts/run_consistency_check.py` (M4.3) separately validate real-Gemini
judgment quality and repeat-run stability — these need a live API key and
are run manually, not as part of `pytest`.

## 17. Known Limitations

- **Total LLM outage is stored as a genuine Fail verdict**, indistinguishable
  from a real bad answer, rather than being flagged as an evaluation error
  (documented defect D-1, open by design — see
  `docs/evaluation/milestone4_testing.md`).
- **Whitespace-only questions pass schema validation** (defect D-5, low
  severity — the web UI already trims input before submitting).
- **Sequential LLM calls**: each evaluation makes 4 judge calls one after
  another, so batch wall-clock time scales roughly linearly with row count.
- **Batch history** fetches one `/dashboard/stats` call per batch to
  populate its table; fine at the scale exercised, not optimized for a very
  large number of batches.
- **`compute_stats` aggregates in Python**, not SQL `AVG`/`COUNT` — correct
  (independently verified against raw SQL in testing) but means memory use
  scales with the size of the filtered result set.
- **No caching** — repeated identical evaluations re-query the LLM every
  time.
- Judge prompt quality has been validated against a curated 8-case set
  (M2.4) and real-Gemini consistency has a script ready
  (`scripts/run_consistency_check.py`), but neither has been exercised at
  large scale against independent human evaluation.
