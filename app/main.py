from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.api import prompts, health

app = FastAPI(
    title="Prompt Processing System",
    description="Distributed async prompt queue with rate limiting and semantic caching",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add session middleware (use a secure random key in production)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["prompts"])
app.include_router(health.router, prefix="/api/v1/health", tags=["health"])

# Mount the frontend (serves index.html at /)
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
