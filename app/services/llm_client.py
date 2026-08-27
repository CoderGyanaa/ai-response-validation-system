"""
Provider-agnostic LLM client. Judge agents call this instead of talking to
Anthropic/OpenAI SDKs directly, so the provider can be swapped via .env.
"""
import logging
import time

from app.config.settings import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY_SECONDS = 2


class LLMClient:
    def __init__(self) -> None:
        self.provider = settings.LLM_PROVIDER
        self.model = settings.LLM_MODEL

    def complete(self, prompt: str, max_tokens: int = 1000) -> str:
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if self.provider == "anthropic":
                    return self._call_anthropic(prompt, max_tokens)
                elif self.provider == "openai":
                    return self._call_openai(prompt, max_tokens)
                elif self.provider == "gemini":
                    return self._call_gemini(prompt, max_tokens)
                raise ValueError(f"Unsupported LLM_PROVIDER: {self.provider}")
            except Exception as exc:
                last_error = exc
                is_rate_limit = "429" in str(exc) or "rate" in str(exc).lower() or "quota" in str(exc).lower()
                if attempt < MAX_RETRIES and is_rate_limit:
                    delay = BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM call hit rate limit (attempt %d/%d), retrying in %ds: %s",
                        attempt, MAX_RETRIES, delay, exc,
                    )
                    time.sleep(delay)
                    continue
                raise
        raise last_error  # pragma: no cover — unreachable, satisfies type checkers

    def _call_gemini(self, prompt: str, max_tokens: int) -> str:
        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(self.model)
        response = model.generate_content(
            prompt,
            generation_config={"max_output_tokens": max_tokens},
        )
        return response.text

    def _call_anthropic(self, prompt: str, max_tokens: int) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def _call_openai(self, prompt: str, max_tokens: int) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
