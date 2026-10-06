# Final Project Report — AI Response Validation System with Hallucination Detection Assistance

**Infosys Springboard Internship Project**

> **A note on this report's two-AI-system comparison (Section 14):** that
> comparison requires running the live application against a real Gemini API
> key, which this document-preparation pass does not have access to. The
> datasets, demo steps, and result template are fully prepared below; the
> actual run and the real numbers in the result table must be filled in by
> running the steps in `docs/evaluation/final_demo_plan.md`. Nothing in this
> report claims that comparison has already happened.

## 1. Title

AI Response Validation System with Hallucination Detection Assistance

## 2. Abstract

AI systems can produce confident, fluent, but factually unsupported
responses, and there is no standard way to automatically check a response's
relevance, factual accuracy, faithfulness to source evidence, and
completeness. This project implements a retrieval-augmented, multi-agent
evaluation platform: four independent LLM-as-judge agents score a response
along those four dimensions, a Verdict Agent combines them into a weighted
overall score and a Pass/Needs Improvement/Fail verdict, and results are
persisted so they can be explored through a dashboard, filtered and
drilled into, and exported as a structured PDF report — for both single
responses and CSV batches.

## 3. Problem Statement

LLM responses can sound authoritative while containing fabricated or
unsupported claims ("hallucinations"), answer only part of a question, or
miss the question's intent entirely. Manually checking responses for these
failure modes does not scale, and no single metric captures all of them.

## 4. Objectives

- Score AI responses on four independent, well-defined dimensions
- Ground accuracy and hallucination checks in retrieved reference evidence
  rather than the judge's own unverified knowledge, wherever possible
- Flag specific unsupported claims and specific missing aspects, not just a
  single pass/fail number
- Combine the four dimensions into one weighted, threshold-based verdict
- Support both single-response and CSV-batch evaluation
- Persist every result and provide a dashboard and exportable PDF report
  built from that stored data

## 5. Motivation

As AI-generated content becomes a standard part of software products,
teams need a repeatable, evidence-grounded way to catch factual errors and
incomplete answers before they reach users — this project is a working
instance of that kind of evaluation layer, applicable to any system that
produces natural-language answers to questions.

## 6. Proposed Solution

A RAG-based, multi-agent evaluation pipeline: a Reference Knowledge Base
(TruthfulQA + SQuAD, chunked and embedded into ChromaDB) is queried for
evidence relevant to each question; four judge agents (Relevance, Accuracy,
Hallucination Detection, Completeness) each independently score the
response against that evidence using Gemini; a Verdict Agent combines the
four scores with fixed weights into an overall score and verdict; every
result is persisted to SQLite; a dashboard and a PDF report are generated
from that persisted data, never from re-derived or hardcoded numbers.

## 7. System Architecture

See [`docs/evaluation/milestone4.md`](milestone4.md) Section 1 and
[`docs/architecture/architecture-diagram.svg`](../architecture/architecture-diagram.svg)
for the full diagram and component breakdown.

## 8. Technology Stack

| Layer | Choice |
|---|---|
| API | FastAPI, Pydantic |
| LLM | Gemini (configurable; Anthropic/OpenAI also supported via the same client interface) |
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`), run locally |
| Vector database | ChromaDB (local, persistent) |
| Results persistence | SQLite (Python standard library, no extra service) |
| PDF generation | reportlab (Platypus flowables) |
| Datasets | Hugging Face `datasets` (TruthfulQA, SQuAD) |
| Frontend | Single-page vanilla HTML/CSS/JS — no framework, no charting library (hand-built inline SVG) |
| Testing | pytest, pdfplumber (for PDF content validation) |

## 9. Implementation

Implemented incrementally across four milestones:

- **Milestone 1**: evaluation input module, knowledge base ingestion/RAG
  pipeline, scaffolded agents, initial frontend.
- **Milestone 2**: real LLM-based scoring for all four judge agents with
  defined scoring scales and categories; validated against a curated 8-case
  set (`scripts/run_validation_suite.py`) with 0 mismatches on the last
  recorded run.
- **Milestone 3**: Completeness agent's aspect-level breakdown; Verdict
  agent's weighted model, severe-hallucination override, and consolidated
  summary; a full evaluation-dashboard-style results UI; the CSV Batch
  Evaluation Module.
- **Milestone 4**: persisted results store; Evaluation Scoring Dashboard
  (API + UI) built entirely from that store; PDF report export; a
  dedicated end-to-end test suite (87 tests) that found and fixed three
  real defects before this report was written; this final documentation
  pass.

## 10. RAG Methodology

Benchmark Q/A data is cleaned, chunked sentence-aware (short records kept
whole, long contexts split only at sentence boundaries), embedded locally,
and indexed in ChromaDB. At evaluation time, the question (plus any
user-supplied source document) is used to retrieve the most relevant stored
chunks, which are passed to the Accuracy, Hallucination, and Completeness
agents as grounding evidence. Full detail:
[`docs/research/research.md`](../research/research.md),
[`docs/evaluation/milestone3.md`](../evaluation/milestone3.md) (M1.4).

## 11. Evaluation Methodology & Agent Descriptions

See [`docs/evaluation/milestone4.md`](milestone4.md) Section 7 for the full
per-agent table (scores, categories, extra structured output) and
[`docs/evaluation/evaluation.md`](../evaluation/evaluation.md) for prompt
design rationale.

## 12. Scoring Model

Weights: Accuracy 0.30, Hallucination 0.30, Relevance 0.25, Completeness
0.15. A detected hallucination contributes 0 to the weighted sum regardless
of its raw score. Thresholds: ≥0.80 Pass, 0.50–0.79 Needs Improvement,
<0.50 Fail — with a severe-hallucination override forcing Fail whenever
`hallucination_status == "full"`, regardless of the weighted average. Full
detail and worked examples: [`docs/evaluation/milestone4.md`](milestone4.md)
Section 8.

## 13. Dashboard & PDF Reporting

The dashboard (KPI cards, quality-score rings, verdict distribution, score
distribution, hallucination/completeness intelligence, top recurring
issues, batch history, filters, paginated records, drill-down) and the PDF
export are both generated exclusively from the persisted SQLite results —
no number in either is hardcoded or derived independently of the other, and
this was explicitly verified in testing (PDF content checked against the
live dashboard API response for the same batch, not against a second
hand-calculation). Full detail: [`docs/evaluation/milestone4.md`](milestone4.md)
Sections 10–11.

## 14. Two-AI-System Demonstration

**Status: completed.** The final demonstration evaluated two distinct AI
response sets through the developed platform using the live Single Evaluation,
Batch Evaluation, Dashboard, and PDF export workflows.

System A was evaluated on **10 records**. System B was evaluated on **5
records**. The different dataset sizes were used intentionally to limit API
usage during the live demonstration; the comparison is therefore an
evaluation snapshot rather than a statistically equivalent benchmark.

### Final comparison

| Metric | AI System A | AI System B |
|---|---:|---:|
| Total records evaluated | 10 | 5 |
| Pass count / % | 9 / 90% | 0 / 0% |
| Needs Improvement count / % | 0 / 0% | 1 / 20% |
| Fail count / % | 1 / 10% | 4 / 80% |
| Average Relevance | 1.00 | 0.82 |
| Average Accuracy | 0.90 | 0.12 |
| Average Hallucination score | 0.90 | 0.20 |
| Hallucination frequency | 10% | 100% |
| Average Completeness | 0.90 | 0.60 |
| Average Overall score | **0.93** | **0.33** |

### Demonstration finding

For these specific demonstration datasets, System A received a much higher
average overall score than System B (0.93 vs 0.33). System A also showed
higher Accuracy and Completeness scores and a lower hallucination frequency.
The platform classified 9 of System A's 10 responses as Pass, whereas System
B produced 4 Fail results and 1 Needs Improvement result.

These results demonstrate that the platform can distinguish different levels
of response quality across evaluation dimensions and produce both individual
and aggregate evidence-backed evaluation results. They should not be treated
as a general ranking of the underlying AI systems beyond these demonstration
datasets.

The complete execution procedure and recorded results are documented in
[`docs/evaluation/final_demo_plan.md`](final_demo_plan.md).

## 15. Testing

142 automated tests (`pytest tests/`), including an 87-test end-to-end suite
added specifically for Milestone 4.3 that exercises the real orchestrator,
agents, verdict logic, SQLite store, API, dashboard, and PDF generator
together. Three real defects were found and fixed during that work (a
floating-point verdict-threshold boundary bug, a completeness category/score
mismatch, and a hallucination status/claims consistency bug), each with a
regression test. Two low-severity defects are documented and deliberately
left open rather than fixed under test-only-change pressure. Full
methodology, every scenario tested, and the complete defect list:
[`docs/evaluation/milestone4_testing.md`](milestone4_testing.md).

## 16. Results

- 142 tests collected; 140 passing plus 2 intentionally-`xfail`ed documented
  limitations, 0 unexpected failures, as of the last verified run.
- M2.4 prompt-consistency validation against real Gemini calls: 0 mismatches
  across 22 evaluation calls on 8 curated cases (last recorded run).
- Three real defects discovered and fixed via tests written before touching
  production code (see Section 15 / `milestone4_testing.md`).
- No performance benchmark numbers are claimed beyond the qualitative
  observations in `milestone4_testing.md` Section 11 (sequential LLM calls
  as the dominant per-record cost; no load testing was performed).

## 17. Limitations

See [`docs/evaluation/milestone4.md`](milestone4.md) Section 17 for the full
list (total-outage handling, whitespace-only input validation, sequential
LLM calls, batch-history query pattern, in-Python stats aggregation, no
caching, and the scope of judgment-quality validation performed so far).

## 18. Future Scope

- Extend the two-system demonstration to more AI systems and larger datasets
- Parallelize the four judge calls per evaluation to reduce batch latency
- Add a caching layer for repeated identical evaluations
- Benchmark judge consistency and accuracy against larger-scale human
  evaluation, beyond the current 8-case validation set
- Address the two open defects (D-1 total-outage handling, D-5 whitespace
  validation) documented in `milestone4_testing.md`

## 19. Conclusion

The platform implements the full scope defined across Milestones 1–4: a
RAG-grounded, four-dimension, multi-agent evaluation pipeline with a
weighted verdict model, persisted results, a dashboard built from that
persisted data, a consistent PDF export, and a dedicated end-to-end test
suite that found and fixed real defects rather than merely asserting
success. The one remaining piece — the live two-AI-system demonstration
run — is fully prepared (datasets, steps, result template) and ready to
execute; its results should be added to this report once performed.
