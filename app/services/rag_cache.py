"""
app/services/rag_cache.py
All Redis caching for CiteRAG:

  retrieve:{query_hash}:{filter_hash}  → cache retrieval results       (1 hr TTL)
  session:{session_id}                 → chat history / context         (60 min TTL)
  notion_page:{page_id}               → cached Notion page blocks       (6 hr TTL)
  notion_rate:{minute}                → Notion API rate limit counter   (60 sec TTL)
  notion_sync:last_run                → timestamp of last sync          (no TTL)
"""

import json
import hashlib
import logging
from datetime import datetime
from typing import Any

from app.redis_client import get_redis

logger = logging.getLogger("docforge.rag_cache")

# ── TTLs ──────────────────────────────────────────────────────
TTL_RETRIEVAL    = 3600        # 1 hour
TTL_SESSION      = 3600        # 60 minutes
TTL_NOTION_PAGE  = 21600       # 6 hours
TTL_NOTION_RATE  = 60          # 60 seconds
NOTION_RATE_LIMIT = 90         # max Notion API calls per minute


# ── Helpers ───────────────────────────────────────────────────

def _r():
    """Get Redis client — returns None if unavailable."""
    return get_redis()


def _hash(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()[:12]


def _safe_get(key: str) -> Any | None:
    """Get a JSON value from Redis safely."""
    r = _r()
    if not r:
        return None
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.warning(f"Redis GET failed [{key}]: {e}")
        return None


def _safe_set(key: str, value: Any, ttl: int | None = None) -> bool:
    """Set a JSON value in Redis safely."""
    r = _r()
    if not r:
        return False
    try:
        serialized = json.dumps(value, default=str)
        if ttl:
            r.setex(key, ttl, serialized)
        else:
            r.set(key, serialized)
        return True
    except Exception as e:
        logger.warning(f"Redis SET failed [{key}]: {e}")
        return False


# ── 1. Retrieval cache ────────────────────────────────────────
# Key: retrieve:{query_hash}:{filter_hash}
# Caches the result of Milvus vector search + MMR reranking.
# Avoids re-embedding + re-searching for identical queries.

def get_retrieval_cache(query: str, industry: str | None, doc_type: str | None) -> list[dict] | None:
    """Return cached retrieval chunks if available."""
    query_hash  = _hash(query.lower().strip())
    filter_hash = _hash(f"{industry}:{doc_type}")
    key         = f"retrieve:{query_hash}:{filter_hash}"
    result      = _safe_get(key)
    if result:
        logger.info(f"[cache] Retrieval HIT — {key}")
    return result


def set_retrieval_cache(
    query: str,
    industry: str | None,
    doc_type: str | None,
    chunks: list[dict],
) -> None:
    """Cache retrieval chunks for 1 hour."""
    query_hash  = _hash(query.lower().strip())
    filter_hash = _hash(f"{industry}:{doc_type}")
    key         = f"retrieve:{query_hash}:{filter_hash}"
    _safe_set(key, chunks, TTL_RETRIEVAL)
    logger.info(f"[cache] Retrieval SET — {key} ({len(chunks)} chunks)")


# ── 2. Session cache ──────────────────────────────────────────
# Key: session:{session_id}
# Stores chat history + last retrieved chunks for a session.
# Allows multi-turn conversations with context.

def get_session(session_id: str) -> dict | None:
    """Return session data — {messages, last_chunks, created_at}"""
    return _safe_get(f"session:{session_id}")


def set_session(session_id: str, messages: list[dict], last_chunks: list[dict]) -> None:
    """Store/update session for 60 minutes."""
    r = _r()
    if not r:
        return
    key = f"session:{session_id}"
    data = {
        "session_id":  session_id,
        "messages":    messages,
        "last_chunks": last_chunks,
        "updated_at":  datetime.utcnow().isoformat(),
    }
    _safe_set(key, data, TTL_SESSION)

    # Refresh TTL on every interaction so active sessions don't expire
    try:
        r.expire(key, TTL_SESSION)
    except Exception:
        pass


def delete_session(session_id: str) -> None:
    """Delete a session (e.g. on New Chat)."""
    r = _r()
    if not r:
        return
    try:
        r.delete(f"session:{session_id}")
    except Exception:
        pass


# ── 3. Notion page cache ──────────────────────────────────────
# Key: notion_page:{page_id}
# Caches raw Notion page blocks for 6 hours.
# Avoids re-fetching the same page content on every sync.

def get_notion_page_cache(page_id: str) -> list[dict] | None:
    """Return cached Notion blocks for a page."""
    result = _safe_get(f"notion_page:{page_id}")
    if result:
        logger.info(f"[cache] Notion page HIT — {page_id}")
    return result


def set_notion_page_cache(page_id: str, blocks: list[dict]) -> None:
    """Cache Notion page blocks for 6 hours."""
    _safe_set(f"notion_page:{page_id}", blocks, TTL_NOTION_PAGE)
    logger.info(f"[cache] Notion page SET — {page_id} ({len(blocks)} blocks)")


def invalidate_notion_page_cache(page_id: str) -> None:
    """Invalidate cache for a specific page (e.g. after re-ingest)."""
    r = _r()
    if not r:
        return
    try:
        r.delete(f"notion_page:{page_id}")
    except Exception:
        pass


# ── 4. Notion rate limit counter ──────────────────────────────
# Key: notion_rate:{minute}
# Tracks how many Notion API calls have been made in the current minute.
# Notion allows ~3 requests/sec = ~180/min, we cap at 90 to be safe.

def check_notion_rate_limit() -> bool:
    """
    Returns True if we're within rate limit, False if exceeded.
    Increments the counter for the current minute.
    """
    r = _r()
    if not r:
        return True  # If Redis unavailable, allow the call

    minute_key = f"notion_rate:{datetime.utcnow().strftime('%Y%m%d%H%M')}"
    try:
        count = r.incr(minute_key)
        if count == 1:
            r.expire(minute_key, TTL_NOTION_RATE)

        if count > NOTION_RATE_LIMIT:
            logger.warning(f"[cache] Notion rate limit hit — {count} calls this minute")
            return False
        return True
    except Exception:
        return True  # Allow on Redis error


def get_notion_rate_count() -> int:
    """Return current minute's Notion API call count."""
    r = _r()
    if not r:
        return 0
    minute_key = f"notion_rate:{datetime.utcnow().strftime('%Y%m%d%H%M')}"
    try:
        val = r.get(minute_key)
        return int(val) if val else 0
    except Exception:
        return 0


# ── 5. Last sync timestamp ────────────────────────────────────
# Key: notion_sync:last_run
# Stores ISO timestamp of last successful full ingest.
# No TTL — persists until manually cleared or overwritten.

def set_last_sync() -> None:
    """Mark the current time as the last successful sync."""
    _safe_set("notion_sync:last_run", datetime.utcnow().isoformat(), ttl=None)
    logger.info("[cache] notion_sync:last_run updated")


def get_last_sync() -> str | None:
    """Return ISO timestamp of last successful sync."""
    return _safe_get("notion_sync:last_run")


# ── Cache stats (for debugging) ───────────────────────────────

def get_cache_stats() -> dict:
    """Return overview of all RAG cache keys."""
    r = _r()
    if not r:
        return {"redis_available": False}
    try:
        retrieval_keys  = len(r.keys("retrieve:*"))
        session_keys    = len(r.keys("session:*"))
        notion_pg_keys  = len(r.keys("notion_page:*"))
        rate_count      = get_notion_rate_count()
        last_sync       = get_last_sync()
        return {
            "redis_available":    True,
            "retrieval_cached":   retrieval_keys,
            "active_sessions":    session_keys,
            "notion_pages_cached": notion_pg_keys,
            "notion_calls_this_minute": rate_count,
            "last_sync":          last_sync,
        }
    except Exception as e:
        return {"redis_available": True, "error": str(e)}