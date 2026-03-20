"""
app/routes/sync.py
POST /sync/run  — triggers full Notion → Milvus ingest.
GET  /sync/status — returns collection stats.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from datetime import datetime

from app.services.ingest_service import ingest_all
from app.rag_config import collection_stats
from app.redis_client import get_redis
from app.services.rag_cache import set_last_sync, get_last_sync, get_cache_stats

router = APIRouter(prefix="/sync", tags=["Sync"])



def _run_ingest():
    """Background task — runs full ingest and stores timestamp in Redis."""
    try:
        result = ingest_all()
        set_last_sync()   # store via rag_cache
        print(f"[sync] Ingest complete: {result}")
    except Exception as e:
        print(f"[sync] Ingest failed: {e}")


@router.post("/run")
def run_sync(background_tasks: BackgroundTasks):
    """
    Trigger a full knowledge base sync in the background.
    Returns immediately — sync runs async.
    """
    background_tasks.add_task(_run_ingest)
    return {
        "message": "Sync started",
        "status":  "running",
    }


@router.get("/status")
def sync_status():
    """Return collection stats + last sync timestamp."""
    stats    = collection_stats()
    last_run = get_last_sync()
    return {
        "collection_exists": stats["exists"],
        "docs_indexed":      stats["count"],
        "last_sync":         last_run,
    }


@router.get("/cache-stats")
def cache_stats():
    """Return Redis cache statistics for all RAG cache keys."""
    return get_cache_stats()