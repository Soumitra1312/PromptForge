import pytest
from app.services.rate_limiter import RateLimiter, RateLimitExceeded


@pytest.fixture
def session_dict():
    """In-memory dict for rate limiter state."""
    return {}


@pytest.mark.asyncio
async def test_acquire_token_allowed(session_dict):
    """Token available → acquire should succeed immediately."""
    limiter = RateLimiter(session_dict, max_tokens=300, refill_rate=5.0)
    await limiter.acquire()  # Should not raise


@pytest.mark.asyncio
async def test_acquire_token_denied_then_allowed(session_dict):
    """Token denied then replenished → should retry and succeed."""
    limiter = RateLimiter(session_dict, max_tokens=1, refill_rate=10.0)
    # First acquire consumes the token
    await limiter.acquire()
    assert session_dict["rate:llm_provider"]["tokens"] == 0
    # Wait a bit for refill
    import time
    time.sleep(0.15)
    # Second acquire should succeed after refill
    await limiter.acquire()


@pytest.mark.asyncio
async def test_acquire_token_timeout(session_dict):
    """Token depleted → should raise RateLimitExceeded after timeout."""
    limiter = RateLimiter(session_dict, max_tokens=1, refill_rate=0)  # No refill
    await limiter.acquire()  # Consume the token
    with pytest.raises(RateLimitExceeded):
        await limiter.acquire(max_wait_seconds=0.01)


@pytest.mark.asyncio
async def test_get_remaining_tokens(session_dict):
    limiter = RateLimiter(session_dict, max_tokens=300)
    session_dict["rate:llm_provider"] = {"tokens": 250.5, "last_refill": 0}
    remaining = await limiter.get_remaining_tokens()
    assert remaining == 250.5


@pytest.mark.asyncio
async def test_get_remaining_tokens_empty(session_dict):
    """No data in state → return max_tokens."""
    limiter = RateLimiter(session_dict, max_tokens=300)
    remaining = await limiter.get_remaining_tokens()
    assert remaining == 300.0
