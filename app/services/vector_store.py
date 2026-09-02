"""
Thin wrapper around ChromaDB so the rest of the app doesn't depend on the
vector DB library directly (makes it swappable later).
"""

from app.config.settings import settings


class VectorStore:
    def __init__(self) -> None:
        import chromadb
        from chromadb.utils import embedding_functions

        self.client = chromadb.PersistentClient(
            path=settings.VECTOR_DB_PATH
        )

        embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.EMBEDDING_MODEL
        )

        self.collection = self.client.get_or_create_collection(
            name="knowledge_base",
            embedding_function=embedding_fn,
        )

    def add(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

    def query(
        self,
        query_text: str,
        top_k: int = 5,
    ) -> list[str]:
        results = self.collection.query(
            query_texts=[query_text],
            n_results=top_k,
        )

        return results.get("documents", [[]])[0]

    def count(self) -> int:
        return self.collection.count()