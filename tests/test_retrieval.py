"""
Retrieval quality test for M1.4.

Uses a temporary ChromaDB path with synthetic fixture data shaped like the
real ingestion output (TruthfulQA/SQuAD-style records), so this runs without
a network call to Hugging Face — only the local embedding model is needed
(already cached after running scripts/ingest_knowledge_base.py once).
"""
from app.config.settings import settings
from app.services.vector_store import VectorStore


def test_retrieval_returns_paris_for_capital_of_france_question(tmp_path):
    settings.VECTOR_DB_PATH = str(tmp_path / "chroma_test")
    store = VectorStore()

    store.add(
        ids=["truthfulqa-0-chunk0", "squad-0-chunk0", "squad-1-chunk0"],
        documents=[
            "Q: What is the capital of France?\nA: Paris is the capital of France.",
            "Context: France is a country in Western Europe. Its capital and "
            "largest city is Paris.\nQ: What is the capital city of France?\nA: Paris",
            "Context: Germany is a country in Central Europe. Its capital is "
            "Berlin.\nQ: What is the capital of Germany?\nA: Berlin",
        ],
        metadatas=[
            {"dataset": "truthful_qa"},
            {"dataset": "squad"},
            {"dataset": "squad"},
        ],
    )

    results = store.query("What is the capital of France?", top_k=2)

    assert len(results) > 0
    assert any("paris" in r.lower() for r in results), (
        f"Expected retrieved evidence to mention Paris, got: {results}"
    )
