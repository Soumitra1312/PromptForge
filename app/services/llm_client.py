import logging
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)
from app.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Groq LLM client.
    Model is configured via settings.LLM_MODEL (e.g. 'llama3-70b-8192').
    """

    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.model = settings.LLM_MODEL
        self.base_url = "https://api.groq.com/openai/v1"

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def complete(self, prompt: str, max_tokens: int = 500) -> str:
        """Call Groq LLM API with automatic retries on transient errors."""

        # Groq requires max_tokens to be at least 1 and within model limits
        max_tokens = max(1, min(int(max_tokens), 4096))

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }

        logger.info("Calling Groq model=%s max_tokens=%d", self.model, max_tokens)

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if not response.is_success:
                # Log the full Groq error body so we can see exactly what's wrong
                try:
                    error_body = response.json()
                except Exception:
                    error_body = response.text
                logger.error(
                    "Groq API %d error: %s", response.status_code, error_body
                )
                response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"] or ""
            logger.info("Groq response received (%d chars)", len(content))
            return content