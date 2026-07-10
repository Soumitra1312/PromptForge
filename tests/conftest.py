import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.config import settings


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.eval = AsyncMock(return_value=1)
    redis.hget = AsyncMock(return_value=None)
    redis.hset = AsyncMock(return_value=1)
    redis.keys = AsyncMock(return_value=[])
    redis.llen = AsyncMock(return_value=0)
    redis.lpop = AsyncMock(return_value=None)
    redis.rpush = AsyncMock(return_value=1)
    return redis


@pytest.fixture
async def client(mock_redis):
    """FastAPI test client."""
    from fastapi.testclient import TestClient
    from httpx import AsyncClient
    from app.main import app

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def worker(mock_redis):
    """Mock worker instance."""
    from app.workers.worker import Worker
    
    w = Worker(
        worker_id="test-worker:1234",
        redis=mock_redis,
        db_url=settings.DATABASE_URL,
        num_workers=1
    )
    w.redis = mock_redis
    return w
