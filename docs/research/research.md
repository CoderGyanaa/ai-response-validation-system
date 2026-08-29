# Research Notes — Core Concepts

Plain-English explanations of the concepts underpinning this project, per Milestone 1.1.

## LLM Evaluation
Judging how good an AI-generated response is — not just "does it run," but "is it correct, relevant, and complete." Unlike traditional software testing (fixed expected output), LLM outputs are open-ended text, so evaluation needs its own methods (this project uses another LLM as the judge — see "LLM-as-a-Judge" below).

## Hallucination Detection
A "hallucination" is when an LLM states something as fact that isn't actually supported by any real source — it sounds confident but is fabricated or wrong. Detecting it means comparing each claim in the response against trustworthy evidence and flagging claims that aren't backed up.

*Example*: If asked "How tall is the Eiffel Tower?" and the model answers "500 meters," but the real answer is 330 meters, that's a hallucination — a confident, specific, wrong claim.

## Factuality vs. Faithfulness
- **Factuality**: is the claim true in the real world?
- **Faithfulness**: is the claim actually supported by the *retrieved evidence* given to the model, regardless of whether it's true in some absolute sense?

These usually align, but not always — a response can be faithful to bad evidence, or factually true by coincidence without being grounded in the evidence provided. This project's Accuracy agent leans toward factuality (checks against reference answer/evidence), and the Hallucination agent leans toward faithfulness (checks against retrieved evidence specifically).

## Relevance
Does the response actually address what was asked — separate from whether it's correct. A response can be 100% relevant (on-topic) and still be 100% wrong (e.g. "The capital of France is Berlin" — directly answers the question, but is factually incorrect).

## Completeness
Does the response cover everything the question asked for? A response can be accurate and relevant but incomplete if it only answers part of a multi-part question.

## RAG (Retrieval-Augmented Generation) Architecture
Instead of relying purely on what an LLM memorized during training, RAG retrieves relevant reference text from a knowledge base *at query time* and gives that text to the LLM as context. This grounds responses in actual retrievable evidence rather than the model's (possibly outdated or wrong) internal knowledge.

*This project's use of RAG*: the knowledge base (TruthfulQA + SQuAD) is chunked and embedded; when evaluating a response, the Retriever pulls the most relevant chunks and hands them to the judge agents as evidence to check claims against.

## Retrieval Pipeline
The process of turning a raw question into relevant reference text:
```
Question → Embed the question → Search vector DB for similar vectors → Return top-K matching chunks
```

## Embeddings
A way of converting text into a list of numbers (a vector) such that texts with similar meaning end up with similar vectors. This lets you compare meaning mathematically (via distance/similarity) instead of just matching exact words.

*Example*: "capital of France" and "France's main city" would have close embeddings even though they share few exact words.

## Semantic Similarity
A measure of how close two pieces of text are in *meaning*, typically computed as the cosine similarity between their embedding vectors. This is what powers retrieval — the vector DB finds chunks whose embeddings are closest to the question's embedding.

## Vector Search
Searching a database of embeddings to find the ones most similar to a query embedding. ChromaDB (used here) handles this efficiently even across thousands of stored chunks.

## LLM-as-a-Judge
Using an LLM itself to evaluate another LLM's output, by prompting it with a scoring rubric and asking for a structured verdict (e.g. JSON with a score and reason). This is what all four judge agents in this project do — each sends a purpose-built prompt to Gemini and parses the structured response.

**Caveats** (important — an LLM judge isn't automatically trustworthy):
- **Prompt sensitivity**: small wording changes in the judge prompt can shift scores
- **Bias**: judges can favor longer, more confident-sounding responses regardless of correctness
- **Consistency**: the same input can get different scores across runs (LLMs aren't fully deterministic)
- **Reference-free evaluation** (no ground truth given) is inherently less reliable than reference-based evaluation (comparing against a known-correct answer)

This project mitigates some of this by giving judges retrieved evidence/reference answers when available (reference-based), rather than relying purely on the judge's own knowledge.

## RAGAS
An evaluation framework/library for RAG systems, defining metrics like:
- **Faithfulness**: are response claims supported by retrieved context?
- **Answer relevancy**: does the response address the user's input?
- **Context precision / recall**: how good is the retrieval step itself?

This project's judge agents are inspired by these definitions but implement custom prompts rather than importing the RAGAS library directly, to keep the pipeline transparent and easy to modify for the internship.

## TruLens
Another RAG evaluation framework, centered on concepts like groundedness (similar to faithfulness), context relevance, and answer relevance — conceptually similar to RAGAS.

## TruthfulQA
A benchmark dataset of questions designed to test whether models give truthful answers, specifically including questions humans commonly get wrong due to misconceptions. Used here as one source of reference knowledge.

## SQuAD (Stanford Question Answering Dataset)
A large reading-comprehension dataset: passages of text paired with questions and extracted answers. Used here as a second, larger source of reference knowledge, giving the retriever more grounded context to draw from.

## Evaluation Scoring
In this project, each judge agent returns a score from 0.0–1.0 plus a reason. The Verdict Agent combines these into a weighted overall score (accuracy and hallucination weighted highest, since factual correctness matters most) and maps it to a PASS/PARTIAL/FAIL verdict — see `docs/evaluation/evaluation.md` for the exact scoring design.
