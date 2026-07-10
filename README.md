# PromptForge

⚡ Distributed async prompt processing system for high-volume LLM inference

<div align="center" style="margin-bottom: 20px;">
  <img src="https://cdn.jsdelivr.net/gh/devicons/devicon/icons/python/python-original.svg" height="40" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" height="40" />
  <img src="https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=mongodb&logoColor=white" height="40" />
  <img src="https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logo=groq&logoColor=white" height="40" />
  <img src="https://img.shields.io/badge/asyncio-3776AB?style=for-the-badge&logo=python&logoColor=white" height="40" />
  <img src="https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white" height="40" />
</div>

Handles parallel processing, rate limiting, semantic caching, and crash recovery — all on MongoDB, no Redis required.

## ⚡ Overview

PromptForge is a distributed asynchronous prompt processing system designed for high-volume LLM inference. It enables scalable prompt execution through parallel workers while ensuring reliable processing with rate limiting, semantic caching, priority scheduling, and automatic crash recovery.

The system consists of a FastAPI backend exposing REST APIs, a MongoDB-backed durable job queue, and multiple asynchronous worker processes that execute prompt jobs concurrently. Each worker processes up to 5 concurrent jobs using asyncio.Semaphore, while atomic MongoDB operations prevent duplicate job execution across workers.

To reduce redundant LLM calls, PromptForge uses all-MiniLM-L6-v2 embeddings with cosine similarity–based semantic caching. A token bucket rate limiter supports 300 requests per minute, and an automated recovery mechanism detects jobs stuck for more than 5 minutes, re-queuing them for processing with up to 2 retry attempts before marking them as failed.

PromptForge focuses on building reliable, production-ready AI infrastructure by combining distributed processing, intelligent caching, fault tolerance, and scalable REST APIs to efficiently manage high-throughput LLM workloads.

---

## 📸 Screenshots

| Screenshot 1 | Screenshot 2 |
|---|---|
| ![Screenshot 2026-04-20 202503](Screenshots/Screenshot%202026-04-20%20202503.png) | ![Screenshot 2026-04-20 202537](Screenshots/Screenshot%202026-04-20%20202537.png) |
| Screenshot 3 | Screenshot 4 |
| ![Screenshot 2026-04-20 202903](Screenshots/Screenshot%202026-04-20%20202903.png) | ![Screenshot 2026-04-20 203015](Screenshots/Screenshot%202026-04-20%20203015.png) |

---

## 🏗️ Architecture

```
Client → FastAPI (REST API)
              ↓
         MongoDB (job queue)
              ↓
         Workers (×N parallel)
              ↓
    ┌─────────────────────┐
    │  Semantic Cache      │  ← sentence-transformers + cosine similarity
    │  (MongoDB)           │
    └─────────────────────┘
              ↓
         Groq LLM API
```

| Requirement | Solution |
|---|---|
| REST API | FastAPI with async endpoints |
| Parallel processing | asyncio tasks + Semaphore (5 concurrent jobs) |
| Durable execution | MongoDB job queue with atomic `find_one_and_update` |
| Rate limiting (300 req/min) | Token bucket — global in worker, session-based at API |
| Semantic caching | `all-MiniLM-L6-v2` embeddings + cosine similarity ≥ 0.92 |
| Crash recovery | Stale job recovery — requeues jobs stuck > 5 min |

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/soumitra1312/PromptForge.git
cd PromptForge
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

Create a `.env` file in the project root:

```env
DATABASE_URL=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/promptdb
GROQ_API_KEY=gsk_...
LLM_MODEL=llama-3.3-70b-versatile
SECRET_KEY=your-random-secret-key
NUM_WORKERS=4
DEBUG=false
```

### 4. Start the system

**Windows** — double-click `start.bat` or run:

```bat
start.bat
```

**Manual start (two terminals):**

```bash
# Terminal 1 — API server
uvicorn app.main:app --reload

# Terminal 2 — Worker
python -m app.workers.worker
```

### 5. Try it out

```bash
# Submit a prompt
curl -X POST http://localhost:8000/api/v1/prompts \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain quantum computing in 3 sentences"}'

# Response:
# {"job_id": "abc-123", "status": "pending", "cache_hit": false, "position_in_queue": 1}

# Poll for status
curl http://localhost:8000/api/v1/prompts/abc-123

# Get result once completed
curl http://localhost:8000/api/v1/prompts/abc-123/result

# Cancel a pending job
curl -X DELETE http://localhost:8000/api/v1/prompts/abc-123

# System health
curl http://localhost:8000/api/v1/health
```

---

## 📡 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/prompts` | Submit a prompt job |
| `GET` | `/api/v1/prompts/{job_id}` | Poll job status |
| `GET` | `/api/v1/prompts/{job_id}/result` | Get completed result |
| `DELETE` | `/api/v1/prompts/{job_id}` | Cancel a pending job |
| `GET` | `/api/v1/health` | System health + queue depth |

### Submit Prompt — Request Body

```json
{
  "prompt": "Your prompt text here",
  "priority": "normal",
  "max_tokens": 500,
  "cache_ttl_seconds": 3600
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `prompt` | string | required | The prompt text (1–10,000 chars) |
| `priority` | `normal` \| `high` | `normal` | High priority jobs skip the cache and are processed first |
| `max_tokens` | int | 500 | Max tokens in LLM response (1–4096) |
| `cache_ttl_seconds` | int | 3600 | How long to cache the result (0 = no cache) |

### Job Statuses

```
pending → processing → completed
                     → failed
         cancelled
```

---

## ⚙️ How It Works

### Rate Limiting
A token bucket is maintained per worker process (global shared dict) and per API session. The bucket refills at **5 tokens/second** (300/minute). If the bucket is empty, the worker re-queues the job and backs off — no requests are silently dropped.

### Semantic Caching
1. Incoming prompt is encoded into a 384-dim vector using `all-MiniLM-L6-v2`
2. The vector is compared against all non-expired cache entries in MongoDB using cosine similarity
3. If similarity ≥ **0.92** → cache hit, stored response returned immediately (no LLM call)
4. If miss → LLM is called, result + embedding stored in `cache_entries` collection with TTL
5. High priority jobs always bypass the cache and go directly to the LLM

### Parallel Processing
Each worker runs up to **5 concurrent jobs** via `asyncio.Semaphore(5)`. Jobs are claimed atomically with `find_one_and_update` — no two workers can claim the same job. New jobs are picked up immediately in a loop while existing ones run in the background.

### Priority Queue
Jobs have a `priority_order` field: `high = 0`, `normal = 1`. MongoDB sorts by `(priority_order ASC, created_at ASC)` — high priority jobs are always processed first.

### Crash Recovery
Every 60 loop ticks, the worker scans for jobs stuck in `processing` for more than **5 minutes** (indicating a crashed worker) and resets them to `pending` for reprocessing. Jobs are retried up to **2 times** before being permanently marked `failed`.

---

## 📁 Project Structure

```
PromptForge/
├── app/
│   ├── main.py                  # FastAPI app + middleware
│   ├── config.py                # Settings loaded from .env
│   ├── api/
│   │   ├── prompts.py           # Prompt CRUD endpoints
│   │   └── health.py            # Health check endpoint
│   ├── services/
│   │   ├── semantic_cache.py    # Embedding + cosine similarity cache
│   │   ├── rate_limiter.py      # Token bucket rate limiter
│   │   └── llm_client.py        # Groq LLM client with retries
│   ├── workers/
│   │   └── worker.py            # Async job processor with crash recovery
│   └── db/
│       ├── mongo.py             # Motor async MongoDB client
│       └── models.py            # Data models
├── frontend/                    # Static frontend (served at /)
├── tests/
│   ├── test_api.py
│   ├── test_cache.py
│   ├── test_rate_limiter.py
│   └── test_worker.py
├── requirements.txt
├── start.bat                    # One-click Windows startup
└── .env                         # Environment variables (not committed)
```

---

## 🔑 Environment Variables

| Variable | Example | Description |
|---|---|---|
| `DATABASE_URL` | `mongodb+srv://user:pass@host/db` | **Required.** MongoDB connection string |
| `GROQ_API_KEY` | `gsk_...` | **Required.** Groq API key |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | LLM model to use |
| `SECRET_KEY` | `some-random-string` | Session middleware secret |
| `NUM_WORKERS` | `4` | Number of parallel worker processes |
| `DEBUG` | `false` | Enable verbose logging |

---

## ✅ Running Tests

```bash
pytest --cov=app -v
```

---

## 🧰 Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI + Uvicorn |
| Database | MongoDB (via Motor async driver) |
| LLM Provider | Groq (`llama-3.3-70b-versatile`) |
| Semantic Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) |
| Similarity Search | NumPy cosine similarity |
| Retries | Tenacity |
| HTTP Client | HTTPX |
