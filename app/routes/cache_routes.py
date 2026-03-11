import logging
from fastapi import APIRouter
from app.redis_client import get_redis

logger = logging.getLogger("docforge.cache")
router = APIRouter(prefix="/cache", tags=["Cache"])


@router.delete("/bust")
def bust_cache():
    """Clear all DocForge cached data (departments + all templates)."""
    r = get_redis()
    if not r:
        return {"message": "Redis not available — nothing to clear"}
    try:
        keys = r.keys("docforge:*")
        if keys:
            r.delete(*keys)
        logger.info(f"Cache busted — {len(keys)} keys cleared")
        return {"message": f"Cache cleared — {len(keys)} keys deleted", "keys": keys}
    except Exception as e:
        return {"message": f"Cache bust failed: {e}"}


@router.get("/status")
def cache_status():
    """Check what's currently cached."""
    r = get_redis()
    if not r:
        return {"redis": "unavailable"}
    try:
        keys = r.keys("docforge:*")
        return {
            "redis": "connected",
            "cached_keys": keys,
            "count": len(keys),
        }
    except Exception as e:
        return {"redis": "error", "detail": str(e)}