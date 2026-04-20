import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.semantic_cache import SemanticCache, cosine_similarity, prompt_hash


def test_cosine_similarity_identical():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_opposite():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(-1.0)


def test_prompt_hash_consistent():
    h1 = prompt_hash("Hello world")
    h2 = prompt_hash("Hello world")
    assert h1 == h2


def test_prompt_hash_case_insensitive():
    h1 = prompt_hash("Hello World")
    h2 = prompt_hash("hello world")
    assert h1 == h2


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    return redis


@pytest.mark.asyncio
async def test_lookup_exact_cache_hit(mock_redis):
    """Exact hash hit in Redis → return without embedding call."""
    mock_redis.get = AsyncMock(return_value="cached response")
    cache = SemanticCache(mock_redis)
    result = await cache.lookup("Hello world")
    assert result == "cached response"


@pytest.mark.asyncio
async def test_lookup_cache_miss(mock_redis):
    """No cache entry → return None (mocking DB with empty results)."""
    mock_redis.get = AsyncMock(return_value=None)
    cache = SemanticCache(mock_redis)

    with patch("app.services.semantic_cache.get_db") as mock_db_ctx:
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_openai = AsyncMock()
        mock_openai.embeddings.create = AsyncMock(
            return_value=MagicMock(data=[MagicMock(embedding=[0.1] * 1536)])
        )
        cache.openai = mock_openai

        result = await cache.lookup("some prompt with no match")
        assert result is None


@pytest.mark.asyncio
async def test_store_caches_in_redis(mock_redis):
    """store() should write to Redis with correct TTL."""
    cache = SemanticCache(mock_redis)

    with patch("app.services.semantic_cache.get_db") as mock_db_ctx:
        mock_db = AsyncMock()
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_openai = AsyncMock()
        mock_openai.embeddings.create = AsyncMock(
            return_value=MagicMock(data=[MagicMock(embedding=[0.1] * 1536)])
        )
        cache.openai = mock_openai

        await cache.store("my prompt", "my response", ttl_seconds=7200)

    mock_redis.setex.assert_called_once()
    args = mock_redis.setex.call_args[0]
    assert args[1] == 7200
    assert args[2] == "my response"
