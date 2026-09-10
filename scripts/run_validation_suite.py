"""
M2.4 — Agent Evaluation & Consistency Validation.

Runs the curated validation test set (docs/evaluation/validation_test_set.py)
through the real Relevance, Accuracy, and Hallucination agents using live
retrieval + Gemini calls, and prints a comparison against the expected
category for each case.

This is a manual review tool, not an automated pass/fail gate — M2.4 asks
for human review of reasoning quality and consistency, not just a score
threshold. Run it, read the output, and use it to spot prompt issues.

RPM-friendly by design:
- Skips the Accuracy call entirely for cases where no accuracy verdict is
  expected (irrelevant/off-topic cases) — no point spending a Gemini call
  scoring accuracy on a response that isn't answering the question.
- Sleeps a configurable delay between every Gemini call (not just between
  cases), so the whole run stays under your model's requests-per-minute cap.
- On a 429, the LLM client (app/services/llm_client.py) now reads Gemini's
  own suggested retry_delay from the error and waits that long, rather than
  guessing with a fixed backoff.

Usage:
    python scripts/run_validation_suite.py
    python scripts/run_validation_suite.py --delay 5      # override delay (seconds) between calls
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.models.schemas import EvaluationRequest
from app.agents.relevance import RelevanceJudgeAgent
from app.agents.accuracy import AccuracyJudgeAgent
from app.agents.hallucination import HallucinationDetectionAgent
from app.retrieval.retriever import Retriever
from docs.evaluation.validation_test_set import VALIDATION_CASES

# Default spacing between Gemini calls. At 15 RPM, the safe minimum is
# 60/15 = 4s; 5s leaves a margin so we don't clip the limit on jitter.
DEFAULT_DELAY_SECONDS = 5.0


def run(delay_seconds: float = DEFAULT_DELAY_SECONDS) -> None:
    retriever = Retriever()
    relevance_agent = RelevanceJudgeAgent()
    accuracy_agent = AccuracyJudgeAgent()
    hallucination_agent = HallucinationDetectionAgent()

    mismatches = 0
    total_checks = 0

    for i, case in enumerate(VALIDATION_CASES):
        request = EvaluationRequest(
            question=case["question"],
            ai_response=case["ai_response"],
            reference_answer=case.get("reference_answer"),
            source_document=case.get("source_document"),
        )
        evidence = retriever.retrieve(request.question, request.source_document)
        expected = case["expected"]

        print(f"\n=== {case['id']} ({case['category']}) ===")
        print(f"Q: {case['question']}")
        print(f"A: {case['ai_response']}")

        # --- Relevance (always evaluated) ---
        relevance = relevance_agent.evaluate(request, evidence)
        time.sleep(delay_seconds)

        print(f"\n  Relevance   : score={relevance.score:.2f}  category={relevance.category!r:22} "
              f"(expected: {expected['relevance']!r})")
        print(f"    reason: {relevance.reason}")
        total_checks += 1
        if expected["relevance"] and relevance.category != expected["relevance"]:
            print("    >>> MISMATCH")
            mismatches += 1

        # --- Accuracy (skipped when no accuracy verdict is expected, e.g.
        #     irrelevant/off-topic cases — saves a Gemini call each time) ---
        if expected["accuracy"] is not None:
            accuracy = accuracy_agent.evaluate(request, evidence)
            time.sleep(delay_seconds)

            print(f"\n  Accuracy    : score={accuracy.score:.2f}  category={accuracy.category!r:22} "
                  f"(expected: {expected['accuracy']!r})")
            print(f"    reason: {accuracy.reason}")
            total_checks += 1
            if accuracy.category != expected["accuracy"]:
                print("    >>> MISMATCH")
                mismatches += 1
        else:
            print("\n  Accuracy    : skipped (no accuracy verdict expected for this case)")

        # --- Hallucination (always evaluated) ---
        hallucination = hallucination_agent.evaluate(request, evidence)
        is_last = i == len(VALIDATION_CASES) - 1
        if not is_last:
            time.sleep(delay_seconds)

        print(f"\n  Hallucination: score={hallucination.score:.2f}  status={hallucination.hallucination_status!r:10} "
              f"(expected: {expected['hallucination_status']!r})")
        print(f"    reason: {hallucination.reason}")
        if hallucination.claim_evidence:
            for fc in hallucination.claim_evidence:
                print(f"    flagged: {fc.claim!r} -- {fc.reason}")
        total_checks += 1
        if hallucination.hallucination_status != expected["hallucination_status"]:
            print("    >>> MISMATCH")
            mismatches += 1

    print(f"\n\n{'='*50}")
    print(f"Total mismatches vs expected category: {mismatches} / {total_checks}")
    print("Review reasoning quality above for cases with a MISMATCH or borderline scores.")
    print("Use this to tune prompts in app/agents/*.py if a pattern of mismatches appears.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the M2.4 validation suite against real agents.")
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY_SECONDS,
        help=f"Seconds to wait between Gemini calls (default: {DEFAULT_DELAY_SECONDS}). "
             "Increase this if you're still hitting RPM limits.",
    )
    args = parser.parse_args()
    run(delay_seconds=args.delay)
