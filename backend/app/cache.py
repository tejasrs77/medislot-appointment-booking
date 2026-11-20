import json
import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException
from redis import Redis, RedisError

from app.core.config import settings

logger = logging.getLogger("medislot.cache")
redis = Redis.from_url(settings.redis_url, socket_connect_timeout=0.2, socket_timeout=0.2,
                       decode_responses=True)
_fallback = defaultdict(deque)
_lock = threading.Lock()


def get(key: str):
    try:
        value = redis.get("medislot:" + key)
        logger.info("cache %s", "hit" if value else "miss")
        return json.loads(value) if value else None
    except (RedisError, ValueError):
        logger.warning("cache unavailable; reading database")
        return None


def put(key: str, value, ttl: int = 30):
    try:
        redis.setex("medislot:" + key, ttl, json.dumps(value))
    except RedisError:
        logger.warning("cache write unavailable")


def invalidate():
    try:
        keys = list(redis.scan_iter("medislot:public:*", count=100))
        if keys:
            redis.delete(*keys)
    except RedisError:
        logger.warning("cache invalidation unavailable; TTL bounds staleness")


def rate_limit(key: str, limit: int = 20, window: int = 60):
    # Atomic increment + expiry; per-process fallback protects a single local worker.
    try:
        count = redis.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then "
                           "redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
                           1, "medislot:rate:" + key, window)
    except RedisError:
        with _lock:
            now = time.monotonic()
            if len(_fallback) > 10000:
                for old in list(_fallback):
                    if not _fallback[old] or _fallback[old][-1] < now - window:
                        del _fallback[old]
            queue = _fallback[key]
            while queue and queue[0] < now - window:
                queue.popleft()
            queue.append(now)
            count = len(queue)
    if count > limit:
        raise HTTPException(429, "Too many requests; try again later", headers={"Retry-After": str(window)})
