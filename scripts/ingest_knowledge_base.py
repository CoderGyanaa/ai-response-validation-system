"""
Ingests benchmark datasets into the local vector store.

Run this once (or whenever you want to rebuild the knowledge base):
    python scripts/ingest_knowledge_base.py

What it does:
1. Downloads TruthfulQA and SQuAD from Hugging Face
2. Cleans + chunks the text (question/answer/context pairs become "documents")
3. Embeds each chunk with a local sentence-transformers model (no API cost)
4. Stores vectors + metadata in ChromaDB at settings.VECTOR_DB_PATH
"""
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))  # allow `app.*` imports

from datasets import load_dataset
import chromadb
from chromadb.utils import embedding_functions

from app.config.settings import settings
from app.config.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

CHUNK_SIZE = 500  # characters per chunk — simple fixed-size chunking for Milestone 1


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Simple fixed-size chunking. Good enough for short QA-style context; can upgrade later."""
    text = text.strip()
    if not text:
        return []
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


def load_truthfulqa() -> list[dict]:
    logger.info("Loading TruthfulQA...")
    ds = load_dataset("truthful_qa", "generation")["validation"]
    records = []
    for i, row in enumerate(ds):
        # best_answer is the reference; question is the query context
        content = f"Q: {row['question']}\nA: {row['best_answer']}"
        records.append({
            "id": f"truthfulqa-{i}",
            "text": content,
            "metadata": {
                "dataset": "truthful_qa",
                "question": row["question"],
                "answer": row["best_answer"],
                "source": "truthful_qa/generation",
            },
        })
    logger.info("Loaded %d TruthfulQA records", len(records))
    return records


def load_squad(limit: int = 2000) -> list[dict]:
    """limit caps how many SQuAD rows we ingest — full dataset is large; cap keeps dev iteration fast."""
    logger.info("Loading SQuAD (limit=%d)...", limit)
    ds = load_dataset("squad")["train"].select(range(limit))
    records = []
    for i, row in enumerate(ds):
        answer_text = row["answers"]["text"][0] if row["answers"]["text"] else ""
        content = f"Context: {row['context']}\nQ: {row['question']}\nA: {answer_text}"
        records.append({
            "id": f"squad-{i}",
            "text": content,
            "metadata": {
                "dataset": "squad",
                "question": row["question"],
                "answer": answer_text,
                "source": "squad/train",
            },
        })
    logger.info("Loaded %d SQuAD records", len(records))
    return records


def build_chunks(records: list[dict]) -> tuple[list[str], list[str], list[dict]]:
    """Turns raw records into (chunk_ids, chunk_texts, chunk_metadatas) for Chroma."""
    ids, texts, metadatas = [], [], []
    for record in records:
        chunks = chunk_text(record["text"])
        for chunk_idx, chunk in enumerate(chunks):
            ids.append(f"{record['id']}-chunk{chunk_idx}")
            texts.append(chunk)
            metadatas.append({
                **record["metadata"],
                "document_id": record["id"],
                "chunk_id": chunk_idx,
            })
    return ids, texts, metadatas


def ingest() -> None:
    client = chromadb.PersistentClient(path=settings.VECTOR_DB_PATH)

    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=settings.EMBEDDING_MODEL
    )
    collection = client.get_or_create_collection(
        name="knowledge_base",
        embedding_function=embedding_fn,
    )

    all_records = load_truthfulqa() + load_squad()
    ids, texts, metadatas = build_chunks(all_records)

    logger.info("Embedding + storing %d chunks...", len(ids))
    batch_size = 500
    for i in range(0, len(ids), batch_size):
        collection.add(
            ids=ids[i:i + batch_size],
            documents=texts[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
        )
        logger.info("Stored batch %d-%d", i, min(i + batch_size, len(ids)))

    logger.info("Ingestion complete. Total chunks in collection: %d", collection.count())


if __name__ == "__main__":
    ingest()
