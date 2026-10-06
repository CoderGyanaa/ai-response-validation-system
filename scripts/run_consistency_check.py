"""
M4.3 — Scoring Consistency Check (requirement 7).

Evaluates the same question/response pair N times through the REAL agents
(live Gemini calls, live retrieval) and reports how much the scores,
categories, and verdict move around.

This needs a live API key and burns real LLM quota, so it is a manual
script, not part of `pytest tests/`. Run it, read the output, and record
the result in docs/evaluation/milestone4_testing.md rather than assuming
consistency.

Because the judge is an LLM, this does NOT demand identical output —
it reports the spread and flags anything that looks like a genuine
inconsistency (e.g. the verdict itself flips) versus normal small
wording/score variation.

Usage:
    python scripts/run_consistency_check.py
    python scripts/run_consistency_check.py --runs 5 --delay 6
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.models.schemas import EvaluationRequest
from app.agents.orchestrator import EvaluationOrchestrator

DEFAULT_RUNS = 5
DEFAULT_DELAY_SECONDS = 6.0

CASE = {
    "question": "What is the capital of France?",
    "ai_response": "The capital of France is Paris.",
    "reference_answer": "Paris",
    "source_document": "France is a country in Europe. Its capital city is Paris.",
}


def run(n_runs: int, delay_seconds: float) -> None:
    orchestrator = EvaluationOrchestrator()
    request = EvaluationRequest(**CASE)

    results = []
    for i in range(n_runs):
        result = orchestrator.run(request)
        results.append(result)
        print(f"\n=== Run {i + 1}/{n_runs} ===")
        print(f"  Relevance    : {result.relevance.score:.2f}  {result.relevance.category}")
        print(f"  Accuracy     : {result.accuracy.score:.2f}  {result.accuracy.category}")
        print(f"  Hallucination: {result.hallucination.score:.2f}  {result.hallucination.hallucination_status}")
        print(f"  Completeness : {result.completeness.score:.2f}  {result.completeness.category}")
        print(f"  Overall      : {result.overall_score:.2f}  ({result.verdict_label})")
        if i < n_runs - 1:
            time.sleep(delay_seconds)

    print(f"\n\n{'='*60}")
    print("CONSISTENCY SUMMARY")
    print(f"{'='*60}")

    verdicts = {r.verdict for r in results}
    overall_scores = [r.overall_score for r in results]
    print(f"Verdicts observed: {verdicts}")
    print(f"Overall score range: {min(overall_scores):.2f} - {max(overall_scores):.2f} "
          f"(spread: {max(overall_scores) - min(overall_scores):.2f})")

    for dim in ("relevance", "accuracy", "completeness"):
        scores = [getattr(r, dim).score for r in results]
        cats = {getattr(r, dim).category for r in results}
        print(f"{dim.capitalize():13s}: scores {min(scores):.2f}-{max(scores):.2f}, categories seen: {cats}")

    hal_statuses = {r.hallucination.hallucination_status for r in results}
    hal_scores = [r.hallucination.score for r in results]
    print(f"{'Hallucination':13s}: scores {min(hal_scores):.2f}-{max(hal_scores):.2f}, statuses seen: {hal_statuses}")

    if len(verdicts) > 1:
        print("\n>>> FLAG: verdict changed across identical-input runs — record this as a real "
              "consistency finding, do not average it away.")
    else:
        print("\nVerdict was stable across all runs. Score/category variation above (if any) is "
              "normal LLM variability, not a defect on its own.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="M4.3 scoring consistency check against the real LLM.")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help=f"Number of repeated evaluations (default: {DEFAULT_RUNS}).")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS, help=f"Seconds between calls (default: {DEFAULT_DELAY_SECONDS}).")
    args = parser.parse_args()
    run(n_runs=args.runs, delay_seconds=args.delay)
