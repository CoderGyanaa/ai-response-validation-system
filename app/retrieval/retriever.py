"""
Retrieves reference evidence for a question from the vector store.

Falls back gracefully if the knowledge base hasn't been ingested yet
(vector store empty or unreachable) so the API doesn't hard-crash —
it just returns less/no evidence, which the judge agents can reason about.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Retriever:
    def __init__(self) -> None:
        self._store = None
        try:
            from app.services.vector_store import VectorStore
            self._store = VectorStore()
        except Exception:
            logger.warning("Vector store unavailable — retrieval will return no evidence.", exc_info=True)

    def retrieve(self, question: str, source_document: Optional[str] = None, top_k: int = 5) -> list[str]:
        evidence: list[str] = []

        if source_document:
            evidence.append(source_document)

        if self._store is not None:
            try:
                results = self._store.query(question, top_k=top_k)
                evidence.extend(results)
            except Exception:
                logger.warning("Vector store query failed — continuing with whatever evidence we have.", exc_info=True)

        return evidence
