import uuid
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import Optional

from app.db.mongo import get_db
from app.services.semantic_cache import SemanticCache
from app.services.rate_limiter import RateLimiter, RateLimitExceeded

router = APIRouter()


class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    priority: str = Field(default="normal", pattern="^(normal|high)$")
    max_tokens: int = Field(default=500, ge=1, le=4096)
    cache_ttl_seconds: Optional[int] = Field(default=3600, ge=0)


class PromptResponse(BaseModel):
    job_id: Optional[str] = None
    status: str
    cache_hit: bool
    position_in_queue: Optional[int] = None
    result: Optional[str] = None


class JobStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


PRIORITY_ORDER = {"high": 0, "normal": 1}


@router.post("", response_model=PromptResponse, status_code=202)
async def submit_prompt(request: Request, body: PromptRequest):
    """Submit a new prompt job. Returns immediately with a job_id."""
    db = get_db()

    limiter = RateLimiter(request.session, max_tokens=300, refill_rate=5.0)
    try:
        await limiter.acquire()
    except RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    cache = SemanticCache(request.session)

    if body.priority == "normal":
        cached_result = await cache.lookup(body.prompt)
        if cached_result:
            return PromptResponse(
                job_id=None,
                status=JobStatus.COMPLETED,
                cache_hit=True,
                result=cached_result,
                position_in_queue=None,
            )

    job_id = str(uuid.uuid4())
    job_doc = {
        "_id": job_id,
        "prompt": body.prompt,
        "status": JobStatus.PENDING,
        "priority": body.priority,
        "priority_order": PRIORITY_ORDER.get(body.priority, 1),
        "max_tokens": body.max_tokens,
        "cache_ttl_seconds": body.cache_ttl_seconds,
        "cache_hit": False,
        "result": None,
        "error_message": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    await db.jobs.insert_one(job_doc)

    queue = request.session.get("job_queue", [])
    queue.append(job_id)
    request.session["job_queue"] = queue
    position = len(queue)

    return PromptResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        cache_hit=False,
        position_in_queue=position,
    )


@router.get("/{job_id}", response_model=PromptResponse)
async def get_job_status(job_id: str):
    """Poll job status."""
    db = get_db()
    job = await db.jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return PromptResponse(
        job_id=job["_id"],
        status=job["status"],
        cache_hit=job.get("cache_hit", False),
        result=job["result"] if job["status"] == JobStatus.COMPLETED else None,
    )


@router.get("/{job_id}/result")
async def get_job_result(job_id: str):
    """Get the completed result for a job."""
    db = get_db()
    job = await db.jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] in [JobStatus.PENDING, JobStatus.PROCESSING]:
        raise HTTPException(status_code=202, detail=f"Job is still {job['status']}")
    if job["status"] == JobStatus.FAILED:
        raise HTTPException(status_code=500, detail=job.get("error_message", "Job failed"))
    return {"job_id": job["_id"], "result": job["result"], "cache_hit": job.get("cache_hit", False)}


@router.delete("/{job_id}", status_code=204)
async def cancel_job(request: Request, job_id: str):
    """Cancel a pending job."""
    db = get_db()
    job = await db.jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != JobStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Cannot cancel a {job['status']} job")
    await db.jobs.update_one({"_id": job_id}, {"$set": {"status": JobStatus.CANCELLED}})

    queue = request.session.get("job_queue", [])
    if job_id in queue:
        queue.remove(job_id)
        request.session["job_queue"] = queue
    return