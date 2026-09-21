from app.models.schemas import JudgeResult, HallucinationResult, CompletenessResult

VERDICT_LABELS = {
    "PASS": "Pass",
    "PARTIAL": "Needs Improvement",
    "FAIL": "Fail",
}


class VerdictAgent:
    """Aggregates individual judge scores into an overall score, verdict, and consolidated reasoning."""

    WEIGHTS = {
        "relevance": 0.25,
        "accuracy": 0.30,
        "hallucination": 0.30,
        "completeness": 0.15,
    }

    def aggregate(
        self,
        relevance: JudgeResult,
        accuracy: JudgeResult,
        hallucination: HallucinationResult,
        completeness: CompletenessResult,
    ) -> dict:
        # Hallucination score is inverted: a detected hallucination contributes 0, not its raw score.
        hallucination_score = 0.0 if hallucination.hallucination_detected else hallucination.score

        overall = (
            relevance.score * self.WEIGHTS["relevance"]
            + accuracy.score * self.WEIGHTS["accuracy"]
            + hallucination_score * self.WEIGHTS["hallucination"]
            + completeness.score * self.WEIGHTS["completeness"]
        )

        if overall >= 0.8:
            verdict = "PASS"
        elif overall >= 0.5:
            verdict = "PARTIAL"
        else:
            verdict = "FAIL"

        # A full-blown hallucination is a critical failure regardless of how the
        # other three dimensions scored — the weighted average alone shouldn't
        # be able to paper over a fabricated, contradicted answer.
        if hallucination.hallucination_status == "full":
            verdict = "FAIL"

        major_issues: list[str] = []
        suggestions: list[str] = []

        if hallucination.hallucination_detected:
            n = len(hallucination.unsupported_claims)
            major_issues.append(
                f"{n} unsupported claim{'s' if n != 1 else ''} detected "
                f"(hallucination status: {hallucination.hallucination_status})."
            )
            suggestions.append("Remove or verify unsupported claims flagged by the hallucination agent.")

        if accuracy.score < 0.5:
            major_issues.append(f"Accuracy judge scored this {accuracy.category or 'low'}: {accuracy.reason}")

        if completeness.missing_aspects:
            major_issues.append(
                f"Missing {len(completeness.missing_aspects)} aspect(s): "
                + "; ".join(completeness.missing_aspects[:3])
            )
            suggestions.append("Address the aspects flagged as missing by the completeness agent.")

        if relevance.score < 0.5:
            major_issues.append(f"Relevance judge found the response {relevance.category or 'not relevant'}.")

        if not major_issues:
            consolidated_summary = (
                f"All four judges scored this response favorably (overall {overall:.2f}). "
                f"No hallucinations, accuracy problems, or missing aspects were identified."
            )
        else:
            consolidated_summary = (
                f"Overall score {overall:.2f} ({VERDICT_LABELS[verdict]}). "
                + " ".join(major_issues)
            )

        return {
            "overall_score": overall,
            "verdict": verdict,
            "verdict_label": VERDICT_LABELS[verdict],
            "major_issues": major_issues,
            "consolidated_summary": consolidated_summary,
            "improvement_suggestions": suggestions,
        }
