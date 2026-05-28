from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.cache import cache_key, get_json, set_json


class DeepSeekClient:
    """Small DeepSeek JSON client with deterministic fallback support.

    Agent nodes pass in a rule-based fallback. This makes the app runnable
    during local demos even before the API key is configured.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    async def complete_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.settings.deepseek_api_key:
            return fallback

        key = cache_key(
            "deepseek-json",
            {
                "model": self.settings.deepseek_model,
                "system": system_prompt,
                "payload": user_payload,
            },
        )
        cached = get_json(key)
        if cached is not None:
            return cached

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.deepseek_model,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": json.dumps(
                                    user_payload, ensure_ascii=False, default=str
                                ),
                            },
                        ],
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                parsed = _parse_json_object(content, fallback)
                set_json(key, parsed)
                return parsed
        except Exception:
            # First version favors a stable product demo over surfacing model
            # transport errors to the UI. Logs/observability can be added later.
            return fallback


def _parse_json_object(content: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            return fallback
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return fallback
