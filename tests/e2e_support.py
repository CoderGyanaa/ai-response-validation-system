"""
Support code for the M4.3 end-to-end tests.

Design: the REAL agents, orchestrator, verdict agent, results store, API,
dashboard endpoints and PDF generator all run. Only the two external
dependencies are replaced:

  * FakeLLM        - replaces LLMClient.complete (the Gemini network call)
  * FakeRetrieval  - replaces Retriever.retrieve (the vector-store query)

Consequence (important for interpreting results): these tests validate
pipeline wiring, data preservation, weighted-score math, verdict rules,
persistence, and dashboard/PDF consistency. They do NOT measure how good
Gemini's judgments are - the "judge" outputs are scripted below. Judgment
quality with the real LLM is covered by scripts/run_validation_suite.py and
scripts/run_consistency_check.py, which need a live API key.

Each scenario carries a hand-calculated expected overall score. Weights are
Relevance 0.25, Accuracy 0.30, Hallucination 0.30 (contribution forced to 0
when a hallucination is detected), Completeness 0.15.
"""
import json

REL_CATS = {"fully_relevant", "partially_relevant", "unrelated", "off_topic"}
ACC_CATS = {"correct", "partially_correct", "incorrect", "contradictory"}
HAL_STATUSES = {"none", "partial", "full"}
COMP_CATS = {"complete", "mostly_complete", "incomplete"}
VERDICT_LABELS = {"PASS": "Pass", "PARTIAL": "Needs Improvement", "FAIL": "Fail"}


def _claim(claim, evidence, reason):
    return {"claim": claim, "supported": False, "evidence": evidence, "reason": reason}


def _llm(rel, rel_cat, acc, acc_cat, hal, hal_status, claims, comp, addressed, missing, reasons=None):
    return {
        "relevance": {"score": rel, "category": rel_cat, "reason": f"Relevance judged {rel_cat}."},
        "accuracy": {"score": acc, "category": acc_cat, "reason": f"Accuracy judged {acc_cat}."},
        "hallucination": {
            "score": hal, "hallucination_status": hal_status, "claims": claims,
            "reason": f"Hallucination status is {hal_status}.",
        },
        "completeness": {
            "score": comp, "addressed_aspects": addressed, "missing_aspects": missing,
            "reason": f"Completeness score {comp}.",
        },
    }


SCENARIOS = {
    "A_correct": {
        "question": "What is the capital of France?",
        "ai_response": "The capital of France is Paris.",
        "reference": "Paris",
        "evidence": ["Paris is the capital of France.", "France is a country in Western Europe."],
        "llm": _llm(1.0, "fully_relevant", 1.0, "correct", 1.0, "none", [], 1.0, ["capital city of France"], []),
        "expected_overall": 1.00, "expected_verdict": "PASS",
    },
    "B_incorrect": {
        "question": "What is the capital of Germany?",
        "ai_response": "The capital of Germany is Munich, and Germany has a population of 50 million.",
        "reference": "Berlin",
        "evidence": ["Berlin is the capital of Germany.", "Germany has about 84 million inhabitants."],
        "llm": _llm(
            1.0, "fully_relevant", 0.0, "contradictory", 0.0, "full",
            [_claim("The capital of Germany is Munich", ["Berlin is the capital of Germany."], "Directly contradicted by the evidence."),
             _claim("Germany has a population of 50 million", ["Germany has about 84 million inhabitants."], "Contradicted by the evidence.")],
            1.0, ["capital city of Germany"], [],
        ),
        "expected_overall": 0.40, "expected_verdict": "FAIL",
    },
    "C_partially_correct": {
        "question": "What is the capital of Italy and what is its population?",
        "ai_response": "The capital of Italy is Rome, and it has a population of about 20 million people.",
        "reference": "Rome; about 2.8 million people",
        "evidence": ["Rome is the capital of Italy.", "Rome has a population of about 2.8 million people."],
        "llm": _llm(
            1.0, "fully_relevant", 0.6, "partially_correct", 0.5, "partial",
            [_claim("it has a population of about 20 million people", ["Rome has a population of about 2.8 million people."], "Contradicted by the retrieved evidence.")],
            1.0, ["capital", "population"], [],
        ),
        "expected_overall": 0.58, "expected_verdict": "PARTIAL",
    },
    "D_incomplete": {
        "question": "List the three primary colors and explain why they are called primary.",
        "ai_response": "Red and blue are primary colors.",
        "reference": "Red, blue and yellow; they cannot be made by mixing other colors",
        "evidence": ["The three primary colors are red, blue and yellow.", "Primary colors cannot be created by mixing other colors."],
        "llm": _llm(
            0.6, "partially_relevant", 0.6, "partially_correct", 1.0, "none", [],
            0.4, ["red as a primary color", "blue as a primary color"],
            ["yellow as the third primary color", "explanation of why they are called primary"],
        ),
        "expected_overall": 0.69, "expected_verdict": "PARTIAL",
    },
    "E_off_topic": {
        "question": "What is the boiling point of water at sea level?",
        "ai_response": "I enjoy playing chess on weekends.",
        "reference": "100 degrees Celsius",
        "evidence": ["Water boils at 100 degrees Celsius at sea level."],
        "llm": _llm(
            0.0, "off_topic", 0.1, "incorrect", 1.0, "none", [],
            0.0, [], ["boiling point of water at sea level"],
        ),
        "expected_overall": 0.33, "expected_verdict": "FAIL",
    },
    "F_unsupported": {
        "question": "Who designed the Eiffel Tower and when did it open?",
        "ai_response": "Gustave Eiffel personally designed it in 1889 and it was privately funded by the Rothschild family.",
        "reference": None,
        "evidence": ["The Eiffel Tower opened in 1889 for the World's Fair.", "The tower is named after the engineering company of Gustave Eiffel."],
        "llm": _llm(
            1.0, "fully_relevant", 0.5, "partially_correct", 0.4, "partial",
            [_claim("it was privately funded by the Rothschild family", [], "No retrieved evidence supports this claim.")],
            0.9, ["designer", "opening year"], [],
        ),
        "expected_overall": 0.535, "expected_verdict": "PARTIAL",
    },
    "G_mixed": {
        "question": "What is the capital of Spain and which river flows through it?",
        "ai_response": "Madrid is the capital of Spain, and the Ebro river flows through the city.",
        "reference": None,
        "evidence": ["Madrid is the capital of Spain.", "The Manzanares river flows through Madrid."],
        "llm": _llm(
            1.0, "fully_relevant", 0.7, "partially_correct", 0.5, "partial",
            [_claim("the Ebro river flows through the city", ["The Manzanares river flows through Madrid."], "The evidence names a different river.")],
            1.0, ["capital", "river"], [],
        ),
        "expected_overall": 0.61, "expected_verdict": "PARTIAL",
    },
    "H_no_reference": {
        "question": "Which ocean is the largest on Earth?",
        "ai_response": "The Pacific Ocean is the largest ocean on Earth.",
        "reference": None,
        "evidence": ["The Pacific Ocean is the largest and deepest ocean on Earth."],
        "llm": _llm(1.0, "fully_relevant", 1.0, "correct", 1.0, "none", [], 1.0, ["largest ocean"], []),
        "expected_overall": 1.00, "expected_verdict": "PASS",
    },
    "K_partially_answered": {
        "question": "Name the capital of Japan and its most famous train service.",
        "ai_response": "Tokyo is the capital of Japan.",
        "reference": None,
        "evidence": ["Tokyo is the capital of Japan.", "The Shinkansen is Japan's famous high-speed train service."],
        "llm": _llm(
            1.0, "fully_relevant", 0.9, "correct", 1.0, "none", [],
            0.6, ["capital of Japan"], ["most famous train service"],
        ),
        "expected_overall": 0.91, "expected_verdict": "PASS",
    },
    "L_substantially_incomplete": {
        "question": "Explain the three states of matter and give an example of each.",
        "ai_response": "Matter exists.",
        "reference": None,
        "evidence": ["The three common states of matter are solid, liquid and gas.", "Ice, water and steam are examples of the three states of water."],
        "llm": _llm(
            0.5, "partially_relevant", 0.6, "partially_correct", 1.0, "none", [],
            0.1, [], ["solid state and example", "liquid state and example", "gas state and example"],
        ),
        "expected_overall": 0.62, "expected_verdict": "PARTIAL",
    },
    "V_vague": {
        "question": "Is it a good idea to invest in index funds?",
        "ai_response": "It depends on many personal factors.",
        "reference": None,
        "evidence": ["Index funds track a market index and typically have low fees."],
        "llm": _llm(
            0.5, "partially_relevant", 0.5, "partially_correct", 1.0, "none", [],
            0.3, [], ["a direct recommendation"],
        ),
        "expected_overall": 0.62, "expected_verdict": "PARTIAL",
    },
    "Z_special_chars": {
        "question": "What is <b>2</b> & 2?",
        "ai_response": "The answer is 4 & that's <final>.",
        "reference": None,
        "evidence": ["2 & 2 equals 4."],
        "llm": _llm(1.0, "fully_relevant", 1.0, "correct", 1.0, "none", [], 1.0, ["the sum"], []),
        "expected_overall": 1.00, "expected_verdict": "PASS",
    },
}


def independent_weighted(llm: dict) -> float:
    """Weighted score recomputed from the scripted judge outputs (documented model)."""
    hallucinated = len(llm["hallucination"]["claims"]) > 0
    hal = 0.0 if hallucinated else llm["hallucination"]["score"]
    return (
        0.25 * llm["relevance"]["score"]
        + 0.30 * llm["accuracy"]["score"]
        + 0.30 * hal
        + 0.15 * llm["completeness"]["score"]
    )


def _agent_of(prompt: str) -> str:
    for marker, agent in (
        ("Relevance Judge", "relevance"),
        ("Accuracy Judge", "accuracy"),
        ("Hallucination Detection Judge", "hallucination"),
        ("Completeness Judge", "completeness"),
    ):
        if marker in prompt:
            return agent
    raise AssertionError("prompt did not come from a known judge agent")


class FakeLLM:
    """Replaces LLMClient.complete. Routes by judge type and by scenario."""

    def __init__(self):
        self.prompts: list[tuple[str, str]] = []  # (agent, prompt) in call order
        self.fail_for: set[str] = set()           # scenario names whose calls should raise

    def match_scenario(self, prompt: str):
        hits = [
            (name, sc) for name, sc in SCENARIOS.items()
            if sc["ai_response"] in prompt and sc["question"] in prompt
        ]
        if not hits:
            return None, None
        return max(hits, key=lambda h: len(h[1]["ai_response"]))

    def __call__(self, llm_self, prompt, max_tokens=1000):
        agent = _agent_of(prompt)
        self.prompts.append((agent, prompt))
        name, sc = self.match_scenario(prompt)
        if sc is None:
            raise AssertionError("no scripted scenario matches this prompt")
        if name in self.fail_for:
            raise RuntimeError("simulated LLM outage")
        return json.dumps(sc["llm"][agent])

    def prompt_for(self, agent: str, index: int = -1) -> str:
        return [p for a, p in self.prompts if a == agent][index]


class FakeRetrieval:
    """Replaces Retriever.retrieve. Mirrors the real contract: source_document first, then store hits."""

    def __init__(self):
        self.enabled = True

    def __call__(self, retriever_self, question, source_document=None, top_k=5):
        evidence = []
        if source_document:
            evidence.append(source_document)
        if self.enabled:
            for sc in SCENARIOS.values():
                if sc["question"] == question:
                    evidence.extend(sc["evidence"])
                    break
        return evidence
