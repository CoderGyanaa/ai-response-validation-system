# Evaluation Methodology

## Evaluation Dimensions

| Dimension | Question it answers | Agent |
|---|---|---|
| Relevance | Does the response address what was asked? | RelevanceJudgeAgent |
| Accuracy | Are the factual claims correct? | AccuracyJudgeAgent |
| Hallucination / Faithfulness | Are claims supported by retrieved evidence? | HallucinationDetectionAgent |
| Completeness | Does the response cover the full question? | CompletenessJudgeAgent |

Each dimension is scored independently by its own LLM-as-judge prompt, then combined into one overall verdict.

## Why Separate Agents Per Dimension

A single "rate this response 1-10" prompt conflates unrelated failure modes — a response can be relevant but inaccurate, or accurate but incomplete. Splitting into four specialized judges makes each prompt simpler and its failure mode more diagnosable (you can tell *which* dimension failed and why, not just get one blended number).

## Agent Prompt Design

Each judge agent (see `app/agents/*.py`) follows the same structure:
1. State the judge's role and what dimension it's scoring
2. Provide the question, AI response, and (where relevant) reference answer / retrieved evidence
3. Give explicit scoring guidance (0.0 = worst, 1.0 = best, with anchor descriptions)
4. Require a strict JSON-only response format

Example (Hallucination agent, simplified):
```
You are a hallucination detection judge. Compare the AI response's claims
against the retrieved evidence. Identify any claims NOT supported by the evidence.

Question: {question}
AI Response: {ai_response}
Retrieved Evidence: {evidence}

Respond with ONLY a JSON object:
{"score": <float>, "hallucination_detected": <bool>, "unsupported_claims": [...], "reason": "..."}
```

Forcing strict JSON output (rather than free text) makes results machine-readable and directly usable in `EvaluationResult`, per the M1 requirement for structured, machine-readable evaluation outputs.

## Handling Missing Evidence

If no evidence was retrieved (empty knowledge base, or a question outside its coverage), agents are instructed not to fabricate a verdict — e.g. the Hallucination prompt explicitly says: "If there is no evidence at all, you cannot verify claims — set hallucination_detected to false... rather than guessing." This avoids false positives when the knowledge base simply doesn't cover a topic.

## Judge Reliability — Known Limitations

Per the internship's evaluation-quality requirements, this project acknowledges (rather than assumes away) LLM-as-judge limitations:

- **Prompt sensitivity**: scores can shift with prompt rewording. Prompts here haven't been formally A/B tested against alternative phrasings.
- **No human-evaluation baseline yet**: judge scores haven't been compared against human-labeled ground truth to measure judge accuracy. This is listed as a Future Improvement.
- **Non-determinism**: repeated calls with the same input can produce slightly different scores, since LLM sampling isn't fully deterministic.
- **Retrieval quality dependency**: judge quality is capped by retrieval quality — if the vector search returns irrelevant chunks, even a perfect judge prompt can't compensate. Retrieval itself hasn't been separately benchmarked (e.g. no context precision/recall metrics computed yet).
- **False positives/negatives**: the Hallucination agent can mislabel a claim as unsupported if retrieval simply missed the relevant evidence, or accept a claim as supported if wording overlaps evidence but the actual entailment is wrong.

## Scoring & Verdict Aggregation

The Verdict Agent (`app/agents/verdict.py`) combines the four scores with fixed weights:

| Dimension | Weight | Rationale |
|---|---|---|
| Accuracy | 30% | Factual correctness is the primary concern |
| Hallucination | 30% | Equally weighted — fabricated claims are as serious as wrong ones |
| Relevance | 25% | An off-topic response fails regardless of internal correctness |
| Completeness | 15% | Important but generally the least severe failure mode |

Special rule: if `hallucination_detected` is `true`, the hallucination dimension's contribution is forced to 0 regardless of its raw score — a detected hallucination should always drag the overall score down, not be softened by a moderate numeric score.

**Verdict thresholds**:
- `overall_score >= 0.8` → **PASS**
- `0.5 <= overall_score < 0.8` → **PARTIAL**
- `overall_score < 0.5` → **FAIL**

These thresholds are a reasonable starting point, not empirically tuned — a good candidate for adjustment once real evaluation examples accumulate.

## Improvement Suggestions

The Verdict Agent also generates plain-language suggestions when specific failure patterns are detected (e.g. "Remove or verify unsupported claims flagged by the hallucination agent" when `hallucination_detected` is true). This is rule-based, not LLM-generated, to keep the output predictable and directly traceable to the judge results.

## Representative Test Cases

`tests/test_agents.py` covers, with mocked LLM responses so tests run deterministically without real API calls:
- Clean JSON parsing (all four agents)
- Markdown-fenced JSON parsing (real-world LLM output quirk)
- Graceful failure when the LLM returns non-JSON text
- Verdict aggregation for a clean PASS case
- Verdict aggregation flagging hallucination-driven suggestions

`tests/test_api.py` covers:
- Valid full evaluation request (end-to-end, real LLM call)
- Missing required field → 422
- Empty question string → 422

**Not yet covered** (candidates for expansion): partially correct responses, empty retrieval, very long responses, LLM/API failure simulation at the orchestrator level, no-reference-answer cases specifically.
