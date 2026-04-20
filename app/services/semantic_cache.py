"""
Semantic cache using sentence-transformers for vector similarity.

How it works:
- Each prompt is encoded into a 384-dim vector using all-MiniLM-L6-v2
- On lookup, we compare the query vector against all cached vectors using cosine similarity
- If similarity >= SIMILARITY_THRESHOLD (0.92), it's a cache hit
"""

import logging
import uuid
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from app.db.mongo import db

logger = logging.getLogger(__name__)


# MODEL CONFIG

MODEL_NAME = "all-MiniLM-L6-v2"
MODEL_PATH = "./models/all-MiniLM-L6-v2"  # optional local persistence
_model = None


def get_model():
    """
    Lazy load the model.
    - If already loaded → reuse
    - If saved locally → load from disk
    - Else → download and save
    """
    global _model

    if _model is not None:
        return _model

    try:
        if os.path.exists(MODEL_PATH):
            logger.info("Loading model from local path...")
            _model = SentenceTransformer(MODEL_PATH)
        else:
            logger.info("Model not found locally. Downloading...")
            _model = SentenceTransformer(MODEL_NAME)

            # Save locally for future runs
            os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
            _model.save(MODEL_PATH)
            logger.info("Model downloaded and saved locally.")

    except Exception as e:
        logger.exception("Failed to load/download model: %s", e)
        raise

    return _model

# EMBEDDING + SIMILARITY

SIMILARITY_THRESHOLD = 0.92

def embed(text: str) -> list[float]:
    """Encode a prompt into a normalized embedding vector."""
    model = get_model()
    return model.encode(text.strip(), normalize_embeddings=True).tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity (dot product since normalized)."""
    return float(np.dot(np.array(a), np.array(b)))

# SEMANTIC CACHE

class SemanticCache:

    def __init__(self, session: dict):
        self.session = session

    async def lookup(self, prompt: str) -> Optional[str]:
        """
        Find most semantically similar cached response.
        """
        try:
            query_vec = embed(prompt)
        except Exception as e:
            logger.warning("Embedding failed, skipping cache: %s", e)
            return None

        try:
            entries = await db.cache_entries.find(
                {"expires_at": {"$gt": datetime.now(timezone.utc)}}
            ).to_list(length=500)
        except Exception as e:
            logger.warning("Cache lookup failed: %s", e)
            return None

        if not entries:
            return None

        best_score = 0.0
        best_entry = None

        for entry in entries:
            embedding = entry.get("embedding")
            if not embedding:
                continue

            try:
                score = cosine_similarity(query_vec, embedding)
            except Exception:
                continue

            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry and best_score >= SIMILARITY_THRESHOLD:
            logger.info(
                "Semantic cache HIT (score=%.4f): %.50s...",
                best_score,
                prompt,
            )
            return best_entry["response_text"]

        logger.info(
            "Semantic cache MISS (best=%.4f < %.2f)",
            best_score,
            SIMILARITY_THRESHOLD,
        )
        return None

    async def store(self, prompt: str, response: str, ttl_seconds: int = 3600) -> None:
        """
        Store prompt + response with embedding.
        """
        try:
            embedding = embed(prompt)
        except Exception as e:
            logger.warning("Embedding failed, skipping cache store: %s", e)
            return

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        entry = {
            "_id": str(uuid.uuid4()),
            "prompt_text": prompt,
            "embedding": embedding,
            "response_text": response,
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc),
        }

        try:
            await db.cache_entries.insert_one(entry)
            logger.info("Stored semantic cache entry: %.50s...", prompt)
        except Exception as e:
            logger.warning("Failed to store cache entry: %s", e)