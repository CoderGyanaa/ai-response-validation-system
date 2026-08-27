from fastapi import FastAPI

from app.config.logging_config import setup_logging
from app.api.routes import router

setup_logging()

app = FastAPI(
    title="AI Response Validation System",
    description="RAG + multi-agent LLM-as-judge hallucination detection API (Infosys Springboard project)",
    version="0.1.0",
)

app.include_router(router)
