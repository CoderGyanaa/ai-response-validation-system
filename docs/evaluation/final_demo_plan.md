# Final Demo Plan — Two-AI-System Evaluation

**Status: completed.** The two-system demonstration was executed through the
live application using the prepared response datasets. System A was evaluated
with 10 records and System B with 5 records. The comparison below uses only
the real batch-evaluation results produced by the application.

## 1. Datasets

[`docs/evaluation/demo_datasets/ai_system_a_responses.csv`](demo_datasets/ai_system_a_responses.csv)
and
[`docs/evaluation/demo_datasets/ai_system_b_responses.csv`](demo_datasets/ai_system_b_responses.csv) —
both verified to parse cleanly against the project's real CSV parser. The
final demonstration used 10 evaluated records for System A and 5 evaluated
records for System B.

Both files answer the **same ten questions**, so the comparison in Section 6
is apples-to-apples. "System A" and "System B" are prepared, representative
response sets for demonstration purposes — not transcripts captured from any
specific named third-party product — covering, by design:

| Row | Category | System A | System B |
|---|---|---|---|
| 1 | Correct | Correct | Correct but padded with a fabricated population figure (hallucination) |
| 2 | Correct | Correct | Incorrect (wrong number) |
| 3 | Correct | Correct | Incorrect (wrong author) |
| 4 | Incorrect | Incorrect (wrong city) | Correct |
| 5 | Incomplete | Incomplete (missing one color) | Irrelevant / off-topic non-answer |
| 6 | Partially correct | Partially correct (missing composition) | Incorrect (wrong composition) |
| 7 | Unsupported/hallucinated | Hallucinated extra details | Substantially incomplete (one-line non-answer) |
| 8 | Correct | Correct | Hallucinated (fabricated, nonsensical claim) |
| 9 | Unsupported/hallucinated | Hallucinated (wrong figure + fabricated attribution) | Hallucinated (wrong figure + fabricated attribution + absurd claim) |
| 10 | Incomplete | Incomplete (count only, no names) | Incorrect (wrong count) |

This gives every required category (correct, incorrect, incomplete,
unsupported/hallucinated, partially correct) in both files, with System B
deliberately weaker so the comparison in Section 6 has something real to
show — but the actual scores and verdicts can only come from running it.

## 2. Step 1 — Single Evaluation

1. Open the app, stay on the **Single Evaluation** tab.
2. Submit one row from `ai_system_a_responses.csv` manually (e.g. row 9, the
   speed-of-light hallucination) by pasting its `question`, `ai_response`,
   and `reference_answer`/`source_document` into the form.
3. Confirm the result view shows: Relevance, Accuracy, Hallucination (with
   the flagged claim, its contradicting evidence, and reasoning),
   Completeness, the weighted overall score, and the final verdict.

## 3. Step 2 — Batch Evaluation (System A)

1. Switch to the **Batch Evaluation** tab.
2. Upload `ai_system_a_responses.csv`.
3. Confirm: all 10 rows are reported valid, progress shows real
   incremental completion (not a fake bar), and the results table populates
   with all 10 verdicts.
4. Note the `batch_id` shown (visible in the Export PDF button's generated
   filename, or via the Dashboard's batch history table) — call it
   **`BATCH_A`**.

## 4. Step 3 — Dashboard

1. Switch to the **Dashboard** tab.
2. Confirm overall KPIs (total evaluated, Pass/Needs Improvement/Fail,
   average dimension scores, hallucination and completeness statistics) are
   visible and non-zero.
3. Use the batch filter to select `BATCH_A` and confirm the filtered stats
   match what Step 2 just produced.
4. Test the verdict filter, a score-range filter, and Reset.
5. Drill into at least one record from the table and confirm it opens the
   full detailed result view.

## 5. Step 4 — Export PDF

1. From the batch history row for `BATCH_A`, click **Export PDF**.
2. Confirm the downloaded PDF contains: the batch summary table, per-
   dimension averages, flagged claims with evidence, missing aspects, the
   improvement recommendations, and a per-record section for all 10 rows.

## Step 5 — Repeat for System B

Repeat Steps 2–4 above using `ai_system_b_responses.csv`, producing a second
`batch_id` — call it **`BATCH_B`**.

## 6. Step 6 — Factual Comparison

The live demonstration was completed. The following values are the actual
results produced by the application's batch evaluation interface.

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

### Interpretation

On these demonstration datasets, System A achieved a substantially higher
overall score (0.93 vs 0.33), higher accuracy (0.90 vs 0.12), higher
completeness (0.90 vs 0.60), and a lower hallucination frequency (10% vs
100%). System A produced 9 Pass results and 1 Fail, while System B produced
4 Fail results and 1 Needs Improvement result.

These results describe this demonstration dataset only and should not be
interpreted as a general ranking of the underlying AI systems.

## Demo Checklist

- [x] Application starts successfully (`uvicorn main:app --reload`)
- [x] Single evaluation works end to end
- [x] Batch evaluation works end to end (System A)
- [x] Batch evaluation works end to end (System B)
- [x] Dashboard loads and reflects real stored data
- [x] Dashboard filters (verdict, batch, score range) work
- [x] Dashboard drill-down opens the full detailed result view
- [x] PDF export works and matches the dashboard for the same batch
- [x] Two distinct AI systems' response sets evaluated (System A, System B)
- [x] Section 6 comparison table filled in from the real batch evaluation results
- [ ] Known limitations (D-1, D-5, and the performance observations in
      `milestone4_testing.md`) mentioned in the live demo narration
