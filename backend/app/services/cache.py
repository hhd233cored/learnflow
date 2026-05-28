from __future__ import annotations

import hashlib
import json
from typing import Any

from redis import Redis

from app.core.config import get_settings

_client: Redis | None = None


def _redis() -> Redis:
    """创建或复用 Redis 客户端。

    设置较短的 socket timeout，可以避免本地开发时 Redis 没启动导致用户请求
    被长时间阻塞。
    """

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
    """根据结构化 payload 生成稳定的缓存 key。"""

    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"studyagent:{prefix}:{digest}"


def get_json(key: str) -> dict[str, Any] | None:
    """从 Redis 读取 JSON 对象；缓存未命中或失败时返回 None。"""

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
    """把 JSON 对象写入 Redis，并设置过期时间。

    缓存只是优化，不是 Agent 输出正确性的前提；因此缓存失败时直接忽略。
    """

    try:
        _redis().setex(
            key,
            ttl_seconds,
            json.dumps(value, ensure_ascii=False, default=str),
        )
    except Exception:
        return
