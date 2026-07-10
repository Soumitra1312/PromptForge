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


@pytest.mark.asyncio
async def test_lookup_returns_best_match_above_threshold():
    """A cached embedding above the similarity threshold should be returned."""
    with patch("app.services.semantic_cache.embed", return_value=[1.0, 0.0]), \
         patch("app.services.semantic_cache.get_db") as mock_get_db:

        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {"embedding": [1.0, 0.0], "response_text": "cached response"}
        ])
        mock_db.cache_entries.find = MagicMock(return_value=mock_cursor)
        mock_get_db.return_value = mock_db

        cache = SemanticCache({})
        result = await cache.lookup("Hello world")

    assert result == "cached response"


@pytest.mark.asyncio
async def test_lookup_cache_miss():
    """No entries above threshold → return None."""
    with patch("app.services.semantic_cache.embed", return_value=[1.0, 0.0]), \
         patch("app.services.semantic_cache.get_db") as mock_get_db:

        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_db.cache_entries.find = MagicMock(return_value=mock_cursor)
        mock_get_db.return_value = mock_db

        cache = SemanticCache({})
        result = await cache.lookup("some prompt with no match")

    assert result is None


@pytest.mark.asyncio
async def test_store_caches_in_mongo():
    """store() should write an entry with prompt, response, and embedding."""
    with patch("app.services.semantic_cache.embed", return_value=[1.0, 0.0]), \
         patch("app.services.semantic_cache.get_db") as mock_get_db:

        mock_db = MagicMock()
        mock_db.cache_entries.insert_one = AsyncMock()
        mock_get_db.return_value = mock_db

        cache = SemanticCache({})
        await cache.store("my prompt", "my response", ttl_seconds=7200)

    mock_db.cache_entries.insert_one.assert_called_once()
    entry = mock_db.cache_entries.insert_one.call_args[0][0]
    assert entry["prompt_text"] == "my prompt"
    assert entry["response_text"] == "my response"
    assert entry["embedding"] == [1.0, 0.0]