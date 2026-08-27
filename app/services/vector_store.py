"""
Thin wrapper around ChromaDB so the rest of the app doesn't depend on the
vector DB library directly (makes it swappable later).
"""
from app.config.settings import settings


class VectorStore:
    def __init__(self) -> None:
        # Imported lazily so the app can boot even before chromadb is installed/configured.
        import chromadb

        self.client = chromadb.PersistentClient(path=settings.VECTOR_DB_PATH)
        self.collection = self.client.get_or_create_collection("knowledge_base")

    def add(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        self.collection.add(ids=ids, documents=documents, metadatas=metadatas)

    def query(self, query_text: str, top_k: int = 5) -> list[str]:
        results = self.collection.query(query_texts=[query_text], n_results=top_k)
        return results.get("documents", [[]])[0]
