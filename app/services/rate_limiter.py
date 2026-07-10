import asyncio
import time


class RateLimitExceeded(Exception):
    pass


class RateLimiter:
    """
    Token bucket rate limiter.
    Default: 300 requests/minute = 5 tokens/second.
    Can be used with a shared dict (worker-level) or session dict (API-level).
    """

    def __init__(
        self,
        session: dict,
        key: str = "rate:llm_provider",
        max_tokens: int = 300,
        refill_rate: float = 5.0,
    ):
        self.session = session
        self.key = key
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate

    async def acquire(self, max_wait_seconds: float = 30.0) -> None:
        deadline = time.monotonic() + max_wait_seconds
        delay = 0.1

        while True:
            now = time.time()
            bucket = self.session.get(
                self.key, {"tokens": self.max_tokens, "last_refill": now}
            )
            tokens = bucket["tokens"]
            last_refill = bucket["last_refill"]

            elapsed = max(0, now - last_refill)
            tokens = min(self.max_tokens, tokens + elapsed * self.refill_rate)

            if tokens >= 1:
                tokens -= 1
                self.session[self.key] = {"tokens": tokens, "last_refill": now}
                return

            if time.monotonic() >= deadline:
                raise RateLimitExceeded(
                    f"Rate limit exceeded after waiting {max_wait_seconds}s"
                )

            await asyncio.sleep(delay)
            delay = min(delay * 2, 5.0)

    async def get_remaining_tokens(self) -> float:
        bucket = self.session.get(self.key, {"tokens": self.max_tokens})
        return float(bucket["tokens"])