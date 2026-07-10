import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_submit_prompt_returns_202(client):
    with patch("app.api.prompts.SemanticCache") as mock_cache_cls, \
         patch("app.api.prompts.get_db") as mock_get_db:

        mock_cache = AsyncMock()
        mock_cache.lookup = AsyncMock(return_value=None)
        mock_cache_cls.return_value = mock_cache

        mock_db = MagicMock()
        mock_db.jobs.insert_one = AsyncMock()
        mock_get_db.return_value = mock_db

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
async def test_submit_prompt_cache_hit(client):
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
    with patch("app.api.prompts.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.jobs.find_one = AsyncMock(return_value=None)
        mock_get_db.return_value = mock_db

        response = await client.get("/api/v1/prompts/nonexistent-id")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_health_check(client):
    with patch("app.api.health.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {"_id": "pending", "count": 2},
            {"_id": "completed", "count": 10},
        ])
        mock_db.jobs.aggregate = MagicMock(return_value=mock_cursor)
        mock_get_db.return_value = mock_db

        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["components"]["mongo"]["status"] == "ok"
    assert data["components"]["mongo"]["job_counts"] == {"pending": 2, "completed": 10}
    assert data["components"]["workers"]["status"] == "n/a"