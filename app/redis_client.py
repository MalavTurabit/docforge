import redis
import logging
from app.config import settings

logger = logging.getLogger("docforge.redis")

CACHE_TTL = 3600  # 1 hour — departments and templates rarely change

try:
    _redis = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    _redis.ping()
    logger.info("Redis connected ✓")
except Exception as e:
    logger.warning(f"Redis unavailable — caching disabled: {e}")
    _redis = None


def get_redis():
    return _redis