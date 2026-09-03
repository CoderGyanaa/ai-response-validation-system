"""
Thin wrapper around ChromaDB so the rest of the app doesn't depend on the
vector DB library directly (makes it swappable later).

IMPORTANT: embeddings are computed manually via sentence-transformers and
passed directly to Chroma (rather than using Chroma's embedding_function
auto-embedding). This avoids a known issue where Chroma falls back to its
own bundled ONNX default embedder on collection reload, which tries to
download a model from Chroma's CDN and can hang/timeout on slow networks.
Computing embeddings ourselves keeps this fully local and deterministic.
"""
from app.config.settings import settings


class VectorStore:
    def __init__(self) -> None:
        # Imported lazily so the app can boot even before these are installed.
        import chromadb
        from sentence_transformers import SentenceTransformer

        self.client = chromadb.PersistentClient(path=settings.VECTOR_DB_PATH)
        self.model = SentenceTransformer(settings.EMBEDDING_MODEL)
        # No embedding_function passed — we always supply embeddings explicitly.
        self.collection = self.client.get_or_create_collection(name="knowledge_base")

    def add(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        embeddings = self.model.encode(documents).tolist()
        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def query(self, query_text: str, top_k: int = 5) -> list[str]:
        query_embedding = self.model.encode([query_text]).tolist()
        results = self.collection.query(query_embeddings=query_embedding, n_results=top_k)
        return results.get("documents", [[]])[0]

    def count(self) -> int:
        return self.collection.count()
