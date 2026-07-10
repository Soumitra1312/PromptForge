from fastapi import APIRouter, Request

from app.db.mongo import get_db

router = APIRouter()

@router.get("")
async def health_check(request: Request):
    """Check health of all system components."""

    status = {"status": "ok", "components": {}}

    queue = request.session.get("job_queue", [])
    status["components"]["session_queue"] = {
        "status": "ok",
        "queue_length": len(queue),
        "job_ids": queue,
    }

    try:
        db = get_db()
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]
        job_counts = await db.jobs.aggregate(pipeline).to_list(length=10)
        counts = {row["_id"]: row["count"] for row in job_counts}
        status["components"]["mongo"] = {"status": "ok", "job_counts": counts}
    except Exception as e:
        status["components"]["mongo"] = {"status": "error", "detail": str(e)}
        status["status"] = "degraded"

    status["components"]["workers"] = {
        "status": "n/a",
        "active_count": None,
    }

    return status