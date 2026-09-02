"""
Diagnostic script — run this from your project root to check retrieval directly.
python test_retrieval.py
"""
from app.services.vector_store import VectorStore

store = VectorStore()
print("Total chunks in collection:", store.count())

results = store.query("What is the capital of France?", top_k=5)
print("\nQuery: 'What is the capital of France?'")
print("Results returned:", len(results))
for i, r in enumerate(results):
    print(f"\n[{i+1}] {r[:200]}")