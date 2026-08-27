"""
Central configuration. Loads values from environment variables (via .env in dev).
Never hardcode secrets here — this file only reads them.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # LLM provider config
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")  # "anthropic" | "openai" | "gemini"
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-1.5-flash")

    # Vector store config
    VECTOR_DB_PATH: str = os.getenv("VECTOR_DB_PATH", "./data/chroma_store")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    # App config
    APP_ENV: str = os.getenv("APP_ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
