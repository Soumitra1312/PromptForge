import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.workers.worker import Worker
from app.db.models import JobStatus


@pytest.fixture
def worker():
    w = Worker()
    w.redis = AsyncMock()
    return w


@pytest.mark.asyncio
async def test_recover_stale_jobs_dead_worker(worker):
    """Jobs stuck in PROCESSING with expired heartbeat should be re-queued."""
    stale_job = MagicMock()
    stale_job.id = "job-123"
    stale_job.status = JobStatus.PROCESSING
    stale_job.worker_id = "dead-worker:9999"
    stale_job.priority = "normal"

    worker.redis.get = AsyncMock(return_value=None)  # heartbeat expired

    with patch("app.workers.worker.get_db") as mock_db_ctx, \
         patch("app.workers.worker.enqueue_job") as mock_enqueue:

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stale_job]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await worker._recover_stale_jobs()

        mock_enqueue.assert_called_once_with(worker.redis, "job-123", priority="normal")
        assert stale_job.status == JobStatus.PENDING
        assert stale_job.worker_id is None


@pytest.mark.asyncio
async def test_recover_stale_jobs_alive_worker(worker):
    """Jobs with a live worker heartbeat should NOT be re-queued."""
    stale_job = MagicMock()
    stale_job.id = "job-456"
    stale_job.status = JobStatus.PROCESSING
    stale_job.worker_id = "alive-worker:1111"

    worker.redis.get = AsyncMock(return_value="1700000000.0")  # heartbeat alive

    with patch("app.workers.worker.get_db") as mock_db_ctx, \
         patch("app.workers.worker.enqueue_job") as mock_enqueue:

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stale_job]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await worker._recover_stale_jobs()

        mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_retry_under_limit(worker):
    """Job under retry limit should be re-queued."""
    job = MagicMock()
    job.id = "job-retry"
    job.retry_count = 1
    job.priority = "normal"

    with patch("app.workers.worker.get_db") as mock_db_ctx, \
         patch("app.workers.worker.enqueue_job") as mock_enqueue, \
         patch("asyncio.sleep", new_callable=AsyncMock):

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=job)
        mock_db.commit = AsyncMock()
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await worker._maybe_retry("job-retry", "connection error", max_retries=3)

        assert job.status == JobStatus.PENDING
        mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_maybe_retry_over_limit(worker):
    """Job over retry limit should be marked FAILED."""
    job = MagicMock()
    job.id = "job-fail"
    job.retry_count = 3
    job.priority = "normal"

    with patch("app.workers.worker.get_db") as mock_db_ctx, \
         patch("app.workers.worker.enqueue_job") as mock_enqueue:

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=job)
        mock_db.commit = AsyncMock()
        mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await worker._maybe_retry("job-fail", "persistent error", max_retries=3)

        assert job.status == JobStatus.FAILED
        mock_enqueue.assert_not_called()
