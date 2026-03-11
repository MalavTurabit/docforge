import json
import logging
from fastapi import APIRouter, Query
from app.db import get_db
from app.redis_client import get_redis, CACHE_TTL

logger = logging.getLogger("docforge.templates")
router = APIRouter(prefix="/templates", tags=["Templates"])


@router.get("/")
def get_templates(dept_id: str = Query(...)):
    r = get_redis()
    cache_key = f"docforge:templates:{dept_id}"

    # ── Try cache first ───────────────────────────────────────
    if r:
        try:
            cached = r.get(cache_key)
            if cached:
                logger.info(f"templates: cache hit for {dept_id}")
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis read failed: {e}")

    # ── Cache miss — fetch from MongoDB ───────────────────────
    logger.info(f"templates: cache miss — fetching {dept_id} from MongoDB")
    db = get_db()
    templates = [
        {"label": doc.get("doc_name"), "id": doc["_id"]}
        for doc in db.document_templates.find({"dept_id": dept_id})
    ]

    # ── Store in cache ────────────────────────────────────────
    if r:
        try:
            r.setex(cache_key, CACHE_TTL, json.dumps(templates))
        except Exception as e:
            logger.warning(f"Redis write failed: {e}")

    return templates