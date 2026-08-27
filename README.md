# AI Response Validation System — Hallucination Detection Assistance

**Infosys Springboard Internship Project — Milestone 1**

## Problem Statement
LLM-generated responses can sound confident while containing unsupported or fabricated claims. There's no standard, automated way to check a response's relevance, factual accuracy, faithfulness to source evidence, and completeness.

## Objective
Build a RAG-based, multi-agent evaluation system that scores AI responses against retrieved reference evidence and flags likely hallucinations.

## Key Features
- Single evaluation submission endpoint (question + AI response, optional reference/source)
- Multi-agent orchestrator: Relevance, Accuracy, Hallucination, Completeness judges + Verdict aggregator — all backed by real LLM scoring (Gemini)
- Reference knowledge base pipeline (TruthfulQA, SQuAD via Hugging Face) → chunk → embed → vector store, with semantic retrieval feeding the judge agents
- Structured, machine-readable JSON evaluation output with per-agent scores, reasons, and unsupported-claims detection
- Retry with exponential backoff for LLM rate limits

## Architecture
```
Client
  ↓
FastAPI (app/api)
  ↓
Evaluation Service (app/evaluation)
  ↓
Retriever (app/retrieval) → Vector Store (app/services/vector_store.py) → ChromaDB
  ↓
Agent Orchestrator (app/agents/orchestrator.py)
  ├── Relevance Judge Agent      → Gemini
  ├── Accuracy Judge Agent       → Gemini
  ├── Hallucination Detection Agent → Gemini
  └── Completeness Judge Agent   → Gemini
  ↓
Verdict Agent → EvaluationResult (JSON)
```

## Agent Responsibilities
| Agent | Purpose | Status |
|---|---|---|
| Relevance | Does the response address the question? | Implemented — LLM-scored |
| Accuracy | Are factual claims correct, checked against retrieved evidence/reference? | Implemented — LLM-scored |
| Hallucination | Are claims supported by evidence? Lists unsupported claims. | Implemented — LLM-scored |
| Completeness | Does the response cover the full question? | Implemented — LLM-scored |
| Verdict | Aggregates weighted scores into overall verdict (PASS/PARTIAL/FAIL) | Implemented |

Each judge agent prompts the LLM for a structured JSON verdict, parses it robustly (handles markdown-fenced output), and fails gracefully with a logged error if the LLM call or parsing fails — a single agent failure doesn't crash the whole evaluation.

## Tech Stack
- **API**: FastAPI + Pydantic
- **LLM**: Gemini (free tier, default) — swappable to Anthropic/OpenAI via `.env`
- **Embeddings**: sentence-transformers (local, no API cost)
- **Vector DB**: ChromaDB (local, persistent)
- **Datasets**: Hugging Face `datasets` (TruthfulQA, SQuAD)
- **Testing**: pytest, with mocked-LLM unit tests for agent logic

## Dataset Sources
See [`data/README.md`](data/README.md) — datasets are not committed, only reproduced via `scripts/ingest_knowledge_base.py`. Currently ingests 817 TruthfulQA records + 2,000 SQuAD records (~5,562 chunks) into the local vector store.

## Project Structure
```
project/
├── app/
│   ├── api/            # FastAPI routes
│   ├── agents/          # orchestrator, 4 judge agents, verdict agent, prompt utils
│   ├── evaluation/       # input validation & service layer
│   ├── retrieval/        # retriever (queries vector store)
│   ├── models/          # Pydantic schemas
│   ├── services/         # LLM client (with retry/backoff), vector store
│   └── config/          # settings, logging
├── data/               # dataset README (no committed data)
├── scripts/            # ingest_knowledge_base.py
├── tests/              # test_api.py, test_agents.py
├── docs/               # architecture / research / evaluation notes
└── main.py             # FastAPI app entrypoint
```

## Installation
```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env       # then fill in your API key
```

## Configuration
Edit `.env` (see `.env.example`):
- `LLM_PROVIDER` — `gemini` (default, free tier), `anthropic`, or `openai`
- `GEMINI_API_KEY` — free key from [Google AI Studio](https://aistudio.google.com/apikey)
- `VECTOR_DB_PATH`, `EMBEDDING_MODEL` — embeddings run locally via sentence-transformers, no API cost

**Cost note:** the default setup (Gemini + local sentence-transformers embeddings + local ChromaDB) needs no paid service to run this project. Gemini's free tier has rate limits; the LLM client retries automatically with backoff.

## Running the Application

1. Build the knowledge base (one-time, or whenever you want to refresh it):
```bash
python scripts/ingest_knowledge_base.py
```
2. Start the API:
```bash
uvicorn main:app --reload
```
Visit `http://127.0.0.1:8000/docs` for interactive API docs.

## Example Evaluation
```bash
curl -X POST http://127.0.0.1:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the capital of France?", "ai_response": "The capital of France is Berlin, and it has a population of 50 million.", "reference_answer": "The capital of France is Paris.", "source_document": "France is a country in Europe. Its capital city is Paris."}'
```

Sample response (real Gemini output):
```json
{
  "relevance": {"score": 1, "reason": "The response directly addresses the question..."},
  "accuracy": {"score": 0, "reason": "The AI response incorrectly states that Berlin is the capital..."},
  "hallucination": {
    "score": 0,
    "hallucination_detected": true,
    "unsupported_claims": ["The capital of France is Berlin", "it has a population of 50 million"]
  },
  "completeness": {"score": 1, "reason": "..."},
  "overall_score": 0.25,
  "verdict": "FAIL"
}
```

## Testing
```bash
pytest tests/ -v
```
11 tests: API-level input validation (`test_api.py`) and agent-level scoring logic with mocked LLM calls, including markdown-fenced JSON parsing and graceful-failure paths (`test_agents.py`).

## Limitations
- Fixed-size chunking (500 chars) — no semantic-aware chunking yet
- No results dashboard yet
- No caching of LLM calls — repeated evaluations re-query the LLM every time
- Judge prompt quality has not been benchmarked against human evaluation

## Future Improvements
- Results dashboard
- Semantic/recursive chunking for the knowledge base
- Human-evaluation comparison for judge reliability and prompt tuning
- Caching layer for repeated evaluations
- Batch evaluation endpoint

## Contributors / Internship Context
Built as part of the Infosys Springboard "AI Response Validation System with Hallucination Detection Assistance" internship project.
