# System Architecture

## High-Level Flow

```
Client (Swagger UI / curl / frontend)
        ↓
FastAPI Backend (app/api/routes.py)
        ↓
Evaluation Service (app/evaluation/service.py)
        ↓
Retriever (app/retrieval/retriever.py)
        ↓
Vector Store / ChromaDB (app/services/vector_store.py)
        ↓
Agent Orchestrator (app/agents/orchestrator.py)
        ├── Relevance Judge Agent
        ├── Accuracy Judge Agent
        ├── Hallucination Detection Agent
        └── Completeness Judge Agent
        ↓
Verdict Agent (app/agents/verdict.py)
        ↓
Structured EvaluationResult (JSON)
        ↓
Response returned to client
```

## Component Responsibilities

### API Layer (`app/api/routes.py`)
- **Purpose**: HTTP interface — exposes `/health` and `/evaluate`
- **Input**: JSON request body matching `EvaluationRequest` schema
- **Processing**: Delegates to `EvaluationService`; converts exceptions to HTTP 500
- **Output**: JSON response matching `EvaluationResult` schema, or FastAPI's automatic 422 for invalid input
- **Dependencies**: `app.evaluation.service`, `app.models.schemas`

### Evaluation Service (`app/evaluation/service.py`)
- **Purpose**: Business-logic entry point for running an evaluation
- **Input**: Validated `EvaluationRequest`
- **Processing**: Invokes the orchestrator, logs failures
- **Output**: `EvaluationResult`
- **Dependencies**: `app.agents.orchestrator`

### Retriever (`app/retrieval/retriever.py`)
- **Purpose**: Fetches reference evidence for a question
- **Input**: question text, optional source_document
- **Processing**: Queries the vector store for semantically similar chunks; falls back to source_document alone (or empty list) if the vector store is unavailable — this keeps the API from crashing when the knowledge base hasn't been built yet
- **Output**: list of evidence strings
- **Dependencies**: `app.services.vector_store`

### Vector Store (`app/services/vector_store.py`)
- **Purpose**: Wraps ChromaDB so the rest of the app doesn't depend on the library directly
- **Input**: text to embed/query
- **Processing**: Uses a local sentence-transformers model to embed text, stores/searches vectors in a persistent ChromaDB collection
- **Output**: nearest-neighbor document chunks
- **Dependencies**: `chromadb`, `sentence-transformers`

### Agent Orchestrator (`app/agents/orchestrator.py`)
- **Purpose**: Coordinates the full evaluation pipeline
- **Input**: `EvaluationRequest`
- **Processing**: Retrieves evidence, runs all four judge agents, passes their results to the Verdict Agent
- **Output**: `EvaluationResult`
- **Dependencies**: `Retriever`, all four judge agents, `VerdictAgent`

### Judge Agents (`app/agents/relevance.py`, `accuracy.py`, `hallucination.py`, `completeness.py`)
- **Purpose**: Each scores one evaluation dimension using an LLM call
- **Input**: `EvaluationRequest` + retrieved evidence
- **Processing**: Builds a prompt (see `docs/evaluation/evaluation.md` for prompt design), calls `LLMClient`, parses the JSON response
- **Output**: `JudgeResult` (or `HallucinationResult` for the hallucination agent)
- **Dependencies**: `app.services.llm_client`, `app.agents.prompt_utils`
- **Failure handling**: any exception (bad LLM output, network error, unparseable JSON) is caught, logged, and converted to a safe fallback result (`score=0.0`, reason explaining the failure) so one agent's failure doesn't crash the whole evaluation

### Verdict Agent (`app/agents/verdict.py`)
- **Purpose**: Aggregates the four judge scores into one overall score and verdict
- **Input**: four `JudgeResult`/`HallucinationResult` objects
- **Processing**: Weighted average (relevance 25%, accuracy 30%, hallucination 30%, completeness 15%); hallucination's contribution is zeroed if `hallucination_detected` is true, regardless of its raw score. Also generates plain-language improvement suggestions.
- **Output**: `(overall_score, verdict_label, suggestions)`
- **Dependencies**: none (pure aggregation logic, no I/O)

### LLM Client (`app/services/llm_client.py`)
- **Purpose**: Provider-agnostic interface for calling an LLM
- **Input**: prompt text
- **Processing**: Routes to Gemini/Anthropic/OpenAI based on `.env` config; retries up to 3 times with exponential backoff (2s/4s/8s) on rate-limit errors; fails immediately on other errors
- **Output**: raw LLM text response
- **Dependencies**: `google-generativeai` / `anthropic` / `openai` SDKs (whichever is configured)

## Data Model (Pydantic Schemas)

| Model | Fields | Used by |
|---|---|---|
| `EvaluationRequest` | question, ai_response, reference_answer?, source_document? | API input |
| `JudgeResult` | agent_name, score, reason, evidence | Relevance, Accuracy, Completeness |
| `HallucinationResult` | (extends JudgeResult) + hallucination_detected, unsupported_claims | Hallucination agent |
| `EvaluationResult` | question, ai_response, relevance, accuracy, hallucination, completeness, overall_score, verdict, improvement_suggestions | API output |

## API Flow (single request)

1. Client POSTs to `/evaluate` with question + ai_response (+ optional reference/source)
2. Pydantic validates the request body (422 if invalid)
3. `EvaluationService.submit_evaluation()` calls the orchestrator
4. Orchestrator calls `Retriever.retrieve()` → queries ChromaDB → returns evidence chunks
5. Orchestrator runs all 4 judge agents sequentially, each making one LLM call
6. `VerdictAgent.aggregate()` combines the 4 scores into an overall verdict
7. `EvaluationResult` is serialized to JSON and returned with HTTP 200

## Known Architectural Trade-offs

- **Sequential agent execution**: the four judge agents run one after another, not in parallel. This is simpler to reason about and debug, but slower (4x LLM latency per request) and more exposed to rate limits. Parallelizing with `asyncio.gather` is a reasonable future improvement.
- **No caching**: identical evaluation requests re-run all four LLM calls every time. Fine for development/testing; would need a cache (e.g. keyed on question+response hash) for production use.
- **Fixed-size chunking**: the knowledge base uses simple 500-character chunks rather than semantic/sentence-aware chunking, which can split evidence mid-sentence. Acceptable for Milestone 1; noted as a future improvement.
