"""
Worker process: pulls jobs from MongoDB, processes them with semantic caching.
No Redis dependency — MongoDB-only design.

Run with: python -m app.workers.worker
"""

import asyncio
import logging
import os
import signal
import socket
from datetime import datetime, timezone, timedelta

from app.services.llm_client import LLMClient
from app.services.semantic_cache import SemanticCache
from app.services.rate_limiter import RateLimiter, RateLimitExceeded

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

# Priority order for sorting: high comes before normal
PRIORITY_ORDER = {"high": 0, "normal": 1}


class Worker:

    def __init__(self):
        self.llm = LLMClient()
        self.running = True
        # Shared bucket across all parallel jobs in this worker process
        # This is what makes rate limiting global instead of per-session
        self._shared_bucket = {}

    async def start(self):
        from app.db.mongo import db

        cache = SemanticCache({})
        semaphore = asyncio.Semaphore(5)  # max 5 parallel jobs at a time
        tick = 0
        logger.info("Worker %s started", WORKER_ID)

        async def process_with_semaphore(job_id):
            async with semaphore:
                await self._process_job(job_id, cache)

        while self.running:
            # Every ~60 loop ticks, recover stale jobs from crashed workers
            tick += 1
            if tick % 60 == 0:
                await self._recover_stale_jobs()

            try:
                # Atomically claim the next highest-priority pending job
                job = await db.jobs.find_one_and_update(
                    {"status": "pending"},
                    {
                        "$set": {
                            "status": "processing",
                            "worker_id": WORKER_ID,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    },
                    sort=[("priority_order", 1), ("created_at", 1)],
                )

                if not job:
                    await asyncio.sleep(1)
                    continue

                # Fire and forget — don't await so we immediately loop back
                # to pick up the next job (parallelism)
                asyncio.create_task(process_with_semaphore(job["_id"]))

            except asyncio.CancelledError:
                logger.info("Worker %s shutting down gracefully.", WORKER_ID)
                break
            except Exception as e:
                logger.exception("Unexpected error in worker loop: %s", e)
                await asyncio.sleep(2)

    async def _process_job(self, job_id: str, cache: SemanticCache):
        from app.db.mongo import db

        logger.info("[%s] Processing job %s", WORKER_ID, job_id)

        job = await db.jobs.find_one({"_id": job_id})
        if not job or job["status"] == "cancelled":
            logger.info("[%s] Job %s skipped (missing or cancelled)", WORKER_ID, job_id)
            return

        if job["status"] not in ("pending", "processing"):
            return

        try:
            # Only check cache for normal priority jobs
            if job.get("priority", "normal") == "normal":
                cached = await cache.lookup(job["prompt"])
                if cached:
                    logger.info("[%s] Cache hit for job %s", WORKER_ID, job_id)
                    await self._complete_job(job_id, cached, cache_hit=True)
                    return

            # Apply global rate limit before hitting the LLM provider
            limiter = RateLimiter(
                self._shared_bucket,   # shared across all jobs — truly global
                max_tokens=300,
                refill_rate=5.0,
            )
            try:
                await limiter.acquire()
            except RateLimitExceeded:
                logger.warning(
                    "[%s] Rate limit hit, re-queuing job %s", WORKER_ID, job_id
                )
                await db.jobs.update_one(
                    {"_id": job_id},
                    {
                        "$set": {
                            "status": "pending",
                            "updated_at": datetime.now(timezone.utc),
                        }
                    },
                )
                return

            result = await self.llm.complete(
                job["prompt"],
                max_tokens=job.get("max_tokens", 500),
            )

            await cache.store(
                job["prompt"],
                result,
                ttl_seconds=job.get("cache_ttl_seconds", 3600),
            )

            await self._complete_job(job_id, result, cache_hit=False)
            logger.info("[%s] Job %s completed", WORKER_ID, job_id)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("[%s] Job %s failed: %s", WORKER_ID, job_id, e)
            await self._maybe_retry(job_id, str(e))

    async def _complete_job(self, job_id: str, result: str, cache_hit: bool):
        from app.db.mongo import db

        await db.jobs.update_one(
            {"_id": job_id},
            {
                "$set": {
                    "status": "completed",
                    "result": result,
                    "cache_hit": cache_hit,
                    "completed_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

    async def _maybe_retry(self, job_id: str, error_message: str):
        from app.db.mongo import db

        job = await db.jobs.find_one({"_id": job_id})
        retry_count = (job.get("retry_count", 0) + 1) if job else 1

        if retry_count > 2:
            await db.jobs.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "failed",
                        "error_message": error_message,
                        "retry_count": retry_count,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )
            logger.warning(
                "[%s] Job %s permanently failed after %d retries",
                WORKER_ID,
                job_id,
                retry_count,
            )
        else:
            await db.jobs.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "pending",
                        "retry_count": retry_count,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )
            logger.info(
                "[%s] Job %s re-queued (attempt %d)", WORKER_ID, job_id, retry_count
            )

    async def _recover_stale_jobs(self):
        """
        Reset jobs stuck in 'processing' for over 5 minutes.
        This handles the case where a worker crashes mid-job —
        those jobs would be stuck as 'processing' forever without this.
        """
        from app.db.mongo import db

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        result = await db.jobs.update_many(
            {"status": "processing", "updated_at": {"$lt": cutoff}},
            {
                "$set": {
                    "status": "pending",
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        if result.modified_count:
            logger.warning(
                "Recovered %d stale jobs from dead workers", result.modified_count
            )


if __name__ == "__main__":

    worker = Worker()

    async def main():
        loop = asyncio.get_running_loop()

        def _stop():
            logger.info("Shutdown signal received, stopping worker...")
            worker.running = False

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _stop)
            except (NotImplementedError, OSError):
                pass

        try:
            await worker.start()
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Worker stopped.")

    asyncio.run(main())