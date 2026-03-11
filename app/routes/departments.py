import json
import logging
from fastapi import APIRouter
from app.db import get_db
from app.redis_client import get_redis, CACHE_TTL

logger = logging.getLogger("docforge.departments")
router = APIRouter(prefix="/departments", tags=["Departments"])

CACHE_KEY = "docforge:depts"


@router.get("/")
def get_departments():
    r = get_redis()

    # ── Try cache first ───────────────────────────────────────
    if r:
        try:
            cached = r.get(CACHE_KEY)
            if cached:
                logger.info("departments: cache hit")
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis read failed: {e}")

    # ── Cache miss — fetch from MongoDB ───────────────────────
    logger.info("departments: cache miss — fetching from MongoDB")
    db = get_db()
    departments = [
        {"dept_id": dept["_id"], "dept_name": dept.get("name")}
        for dept in db.Departments.find({})
    ]

    # ── Store in cache ────────────────────────────────────────
    if r:
        try:
            r.setex(CACHE_KEY, CACHE_TTL, json.dumps(departments))
        except Exception as e:
            logger.warning(f"Redis write failed: {e}")

    return departments