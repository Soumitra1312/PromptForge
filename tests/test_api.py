import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
from app.main import app


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.rpush = AsyncMock(return_value=1)
    redis.llen = AsyncMock(return_value=1)
    redis.lrem = AsyncMock(return_value=0)
    return redis


@pytest.fixture
def client(mock_redis):
    app.state.redis = mock_redis
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_submit_prompt_returns_202(client, mock_redis):
    with patch("app.api.prompts.SemanticCache") as mock_cache_cls, \
         patch("app.api.prompts.get_db") as mock_db_ctx, \
         patch("app.api.prompts.enqueue_job", return_value=1):

        mock_cache = AsyncMock()
        mock_cache.lookup = AsyncMock(return_value=None)
        mock_cache_cls.return_value = mock_cache

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        response = await client.post("/api/v1/prompts", json={
            "prompt": "Explain quantum computing",
            "priority": "normal",
            "max_tokens": 200,
        })

    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "pending"
    assert data["cache_hit"] is False


@pytest.mark.asyncio
async def test_submit_prompt_cache_hit(client, mock_redis):
    with patch("app.api.prompts.SemanticCache") as mock_cache_cls:
        mock_cache = AsyncMock()
        mock_cache.lookup = AsyncMock(return_value="Quantum computing uses qubits...")
        mock_cache_cls.return_value = mock_cache

        response = await client.post("/api/v1/prompts", json={
            "prompt": "Explain quantum computing",
        })

    assert response.status_code == 202
    data = response.json()
    assert data["cache_hit"] is True
    assert data["result"] == "Quantum computing uses qubits..."


@pytest.mark.asyncio
async def test_submit_prompt_validation_error(client):
    response = await client.post("/api/v1/prompts", json={"prompt": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_job_not_found(client):
    with patch("app.api.prompts.get_db") as mock_db_ctx:
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        response = await client.get("/api/v1/prompts/nonexistent-id")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_health_check(client, mock_redis):
    mock_redis.keys = AsyncMock(return_value=["worker:heartbeat:host1:123"])
    mock_redis.llen = AsyncMock(return_value=0)

    with patch("app.api.health.get_db") as mock_db_ctx:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[("pending", 2), ("completed", 10)])
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["components"]["redis"]["status"] == "ok"
    assert data["components"]["workers"]["active_count"] == 1
