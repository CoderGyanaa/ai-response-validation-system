"""
M2.4 — Curated validation test set.

Representative question-answer pairs across response categories, drawn from
TruthfulQA/SQuAD-style facts, used to check that the Relevance, Accuracy,
and Hallucination agents behave consistently and give useful reasoning.

Each case includes an `expected` hint (not enforced automatically — used for
manual/human review per M2.4's requirement to "compare expected evaluation
behavior against actual agent outputs").
"""

VALIDATION_CASES = [
    {
        "id": "correct-01",
        "category": "correct",
        "question": "What is the capital of France?",
        "ai_response": "The capital of France is Paris.",
        "reference_answer": "Paris",
        "source_document": "France is a country in Europe. Its capital city is Paris.",
        "expected": {
            "relevance": "fully_relevant",
            "accuracy": "correct",
            "hallucination_status": "none",
        },
    },
    {
        "id": "incorrect-01",
        "category": "incorrect",
        "question": "What is the capital of France?",
        "ai_response": "The capital of France is Berlin, and it has a population of 50 million.",
        "reference_answer": "Paris",
        "source_document": "France is a country in Europe. Its capital city is Paris.",
        "expected": {
            "relevance": "fully_relevant",
            "accuracy": "contradictory",
            "hallucination_status": "full",
        },
    },
    {
        "id": "partially_correct-01",
        "category": "partially_correct",
        "question": "What is the capital of France and what is its population?",
        "ai_response": "The capital of France is Paris, and it has a population of about 50 million people.",
        "reference_answer": "Paris; population approximately 2.1 million (city proper)",
        "source_document": "Paris is the capital of France. As of recent estimates, the city proper has a population of about 2.1 million.",
        "expected": {
            "relevance": "fully_relevant",
            "accuracy": "partially_correct",
            "hallucination_status": "partial",
        },
    },
    {
        "id": "irrelevant-01",
        "category": "irrelevant",
        "question": "What is the capital of France?",
        "ai_response": "France is known for its cuisine, especially cheese and wine.",
        "reference_answer": "Paris",
        "source_document": "France is a country in Europe. Its capital city is Paris.",
        "expected": {
            "relevance": "unrelated",
            "accuracy": None,
            "hallucination_status": "none",
        },
    },
    {
        "id": "off_topic-01",
        "category": "off_topic",
        "question": "What is the capital of France?",
        "ai_response": "I enjoy playing chess on weekends.",
        "reference_answer": "Paris",
        "source_document": None,
        "expected": {
            "relevance": "off_topic",
            "accuracy": None,
            "hallucination_status": "none",
        },
    },
    {
        "id": "incomplete-01",
        "category": "incomplete",
        "question": "List the three primary colors.",
        "ai_response": "Red and blue are primary colors.",
        "reference_answer": "Red, blue, and yellow",
        "source_document": "The three primary colors are red, blue, and yellow.",
        "expected": {
            "relevance": "partially_relevant",
            "accuracy": "partially_correct",
            "hallucination_status": "none",
        },
    },
    {
        "id": "unsupported_claim-01",
        "category": "unsupported_claim",
        "question": "When did the Eiffel Tower open?",
        "ai_response": "The Eiffel Tower opened in 1889 and was designed to be a permanent government building.",
        "reference_answer": "1889, built as a temporary exhibit for the World's Fair",
        "source_document": "The Eiffel Tower was completed in 1889 for the World's Fair and was originally intended to be temporary.",
        "expected": {
            "relevance": "fully_relevant",
            "accuracy": "partially_correct",
            "hallucination_status": "partial",
        },
    },
    {
        "id": "no_reference-01",
        "category": "no_reference_or_evidence",
        "question": "What is the boiling point of water at sea level in Celsius?",
        "ai_response": "Water boils at 100 degrees Celsius at sea level.",
        "reference_answer": None,
        "source_document": None,
        "expected": {
            "relevance": "fully_relevant",
            "accuracy": "correct",  # judged from the LLM's own knowledge, no evidence to check against
            "hallucination_status": "none",
        },
    },
]
