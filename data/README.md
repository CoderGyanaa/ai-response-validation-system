# Data

This folder is intentionally empty in the repo (see `.gitignore`). Datasets are not committed.

## How to reproduce the knowledge base

Benchmark datasets are pulled from Hugging Face at ingestion time:

```python
from datasets import load_dataset

truthfulqa = load_dataset("truthful_qa", "generation")
squad = load_dataset("squad")
```

Run `scripts/ingest_knowledge_base.py` (to be added in Milestone 1.4) to:
1. Download the datasets above
2. Clean and chunk the text
3. Generate embeddings
4. Store vectors in `data/chroma_store/` (git-ignored, local only)

No raw or processed dataset files should ever be committed to this repository.
