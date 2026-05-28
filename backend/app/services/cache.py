from __future__ import annotations

import hashlib
import json
from typing import Any

from redis import Redis

from app.core.config import get_settings

_client: Redis | None = None


def _redis() -> Redis:
    global _client
    if _client is None:
        settings = get_settings()
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
    return _client


def cache_key(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"studyagent:{prefix}:{digest}"


def get_json(key: str) -> dict[str, Any] | None:
    try:
        value = _redis().get(key)
        if not value:
            return None
        return json.loads(value)
    except Exception:
        # Redis should improve latency and cost, not become a hard dependency
        # for the MVP request path.
        return None


def set_json(key: str, value: dict[str, Any], ttl_seconds: int = 1800) -> None:
    try:
        _redis().setex(
            key,
            ttl_seconds,
            json.dumps(value, ensure_ascii=False, default=str),
        )
    except Exception:
        return

