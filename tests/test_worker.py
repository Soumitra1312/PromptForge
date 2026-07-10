import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_recover_stale_jobs_updates_stuck_jobs(worker):
    """Jobs stuck in 'processing' past the cutoff should be reset to pending."""
    with patch("app.workers.worker.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_db.jobs.update_many = AsyncMock(return_value=mock_result)
        mock_get_db.return_value = mock_db

        await worker._recover_stale_jobs()

        mock_db.jobs.update_many.assert_called_once()
        filter_arg, update_arg = mock_db.jobs.update_many.call_args[0]
        assert filter_arg["status"] == "processing"
        assert update_arg["$set"]["status"] == "pending"


@pytest.mark.asyncio
async def test_recover_stale_jobs_no_stale_jobs(worker):
    """When nothing is stale, update_many still runs but modifies nothing."""
    with patch("app.workers.worker.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_db.jobs.update_many = AsyncMock(return_value=mock_result)
        mock_get_db.return_value = mock_db

        await worker._recover_stale_jobs()

        mock_db.jobs.update_many.assert_called_once()


@pytest.mark.asyncio
async def test_maybe_retry_under_limit(worker):
    """Job under the retry limit (2) should be re-queued as pending."""
    with patch("app.workers.worker.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.jobs.find_one = AsyncMock(return_value={"_id": "job-retry", "retry_count": 1})
        mock_db.jobs.update_one = AsyncMock()
        mock_get_db.return_value = mock_db

        await worker._maybe_retry("job-retry", "connection error")

        mock_db.jobs.update_one.assert_called_once()
        _, update_arg = mock_db.jobs.update_one.call_args[0]
        assert update_arg["$set"]["status"] == "pending"
        assert update_arg["$set"]["retry_count"] == 2


@pytest.mark.asyncio
async def test_maybe_retry_over_limit(worker):
    """Job over the retry limit (2) should be marked failed."""
    with patch("app.workers.worker.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.jobs.find_one = AsyncMock(return_value={"_id": "job-fail", "retry_count": 3})
        mock_db.jobs.update_one = AsyncMock()
        mock_get_db.return_value = mock_db

        await worker._maybe_retry("job-fail", "persistent error")

        _, update_arg = mock_db.jobs.update_one.call_args[0]
        assert update_arg["$set"]["status"] == "failed"
        assert update_arg["$set"]["retry_count"] == 4