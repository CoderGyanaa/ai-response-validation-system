"""
Retrieves reference evidence for a question from the vector store.
Milestone 1: stubbed to return an empty list so the pipeline runs end-to-end
before the knowledge base ingestion pipeline (Milestone 1.4) is implemented.
"""
from typing import Optional


class Retriever:
    def __init__(self) -> None:
        # TODO: initialize vector store client (see app/services/vector_store.py)
        pass

    def retrieve(self, question: str, source_document: Optional[str] = None, top_k: int = 5) -> list[str]:
        # TODO: query vector store for top_k relevant chunks.
        if source_document:
            return [source_document]
        return []
