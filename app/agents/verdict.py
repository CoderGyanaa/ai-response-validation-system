from app.models.schemas import JudgeResult, HallucinationResult


class VerdictAgent:
    """Aggregates individual judge scores into an overall score + verdict label."""

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
        completeness: JudgeResult,
    ) -> tuple[float, str, list[str]]:
        # Hallucination score is inverted: higher hallucination_detected -> lower contribution.
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

        suggestions: list[str] = []
        if hallucination.hallucination_detected:
            suggestions.append("Remove or verify unsupported claims flagged by the hallucination agent.")
        if completeness.score < 0.5:
            suggestions.append("Response may be missing parts of the question — check completeness feedback.")

        return overall, verdict, suggestions
