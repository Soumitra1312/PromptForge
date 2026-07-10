import pytest
from unittest.mock import AsyncMock, patch
from app.services.rate_limiter import RateLimiter, RateLimitExceeded


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    return redis


@pytest.mark.asyncio
async def test_acquire_token_allowed(mock_redis):
    """Token available → acquire should succeed immediately."""
    mock_redis.eval = AsyncMock(return_value=1)
    limiter = RateLimiter(mock_redis, max_tokens=300, refill_rate=5.0)
    await limiter.acquire()  # Should not raise


@pytest.mark.asyncio
async def test_acquire_token_denied_then_allowed(mock_redis):
    """Token denied once, then allowed → should retry and succeed."""
    mock_redis.eval = AsyncMock(side_effect=[0, 0, 1])
    limiter = RateLimiter(mock_redis, max_tokens=300, refill_rate=5.0)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await limiter.acquire(max_wait_seconds=10)
    assert mock_redis.eval.call_count == 3


@pytest.mark.asyncio
async def test_acquire_token_timeout(mock_redis):
    """Always denied → should raise RateLimitExceeded after timeout."""
    mock_redis.eval = AsyncMock(return_value=0)
    limiter = RateLimiter(mock_redis, max_tokens=300, refill_rate=5.0)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(RateLimitExceeded):
            await limiter.acquire(max_wait_seconds=0.01)


@pytest.mark.asyncio
async def test_get_remaining_tokens(mock_redis):
    mock_redis.hget = AsyncMock(return_value="250.5")
    limiter = RateLimiter(mock_redis)
    remaining = await limiter.get_remaining_tokens()
    assert remaining == 250.5


@pytest.mark.asyncio
async def test_get_remaining_tokens_empty(mock_redis):
    """No data in Redis → return max_tokens."""
    mock_redis.hget = AsyncMock(return_value=None)
    limiter = RateLimiter(mock_redis, max_tokens=300)
    remaining = await limiter.get_remaining_tokens()
    assert remaining == 300.0
