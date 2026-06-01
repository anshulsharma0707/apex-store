import json
import os
import redis


# ─── Redis Connection ─────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_TTL  = 30  # seconds

try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
except Exception:
    redis_client = None


# ─── Get from Cache ───────────────────────────────────────────
def cache_get(key: str) -> dict | None:
    if not redis_client:
        return None
    try:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None


# ─── Set in Cache ─────────────────────────────────────────────
def cache_set(key: str, value: dict, ttl: int = CACHE_TTL):
    if not redis_client:
        return
    try:
        redis_client.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass