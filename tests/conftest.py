import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def mock_redis():
    """Mock Redis client — used by rate limiter tests only."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.fixture
async def client():
    """FastAPI test client."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def worker():
    """Worker instance for testing."""
    from app.workers.worker import Worker
    return Worker()