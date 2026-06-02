from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.cache import cache_key, get_json, set_json


class DeepSeekClient:
    """带确定性兜底能力的 DeepSeek JSON 客户端。

    Agent 节点会传入一个规则兜底结果。这样即使还没有配置 API Key，
    应用也能在本地 Demo 中正常运行。
    """

    def __init__(self) -> None:
        """为当前客户端实例加载一次 API 配置。"""

        self.settings = get_settings()

    async def health_check(self) -> dict[str, Any]:
        """直接探测 DeepSeek，不走缓存，也不走规则兜底。

        普通 Agent 路径会在模型不可用时回退到本地规则，以保证 Demo 稳定；
        这个方法更严格，用来确认外部 LLM API 是否真的接通。
        """

        configured = bool(self.settings.deepseek_api_key)
        result: dict[str, Any] = {
            "configured": configured,
            "provider": "deepseek",
            "model": self.settings.deepseek_model,
            "ocr_provider": self.settings.ocr_provider,
            "ocr_enabled": self.settings.ocr_provider.strip().lower() == "paddleocr"
            and bool(self.settings.paddle_ocr_token.strip()),
            "ocr_model": self.settings.paddle_ocr_model,
            "ocr_endpoint": self.settings.paddle_ocr_job_url,
            "ok": False,
            "reply": None,
            "error": None,
        }

        if not configured:
            result["error"] = "DEEPSEEK_API_KEY is not configured"
            return result

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.deepseek_model,
                        "messages": [
                            {
                                "role": "user",
                                "content": "请只回复：DeepSeek API 测试成功",
                            }
                        ],
                    },
                )
                response.raise_for_status()
                payload = response.json()
                result["ok"] = True
                result["reply"] = payload["choices"][0]["message"]["content"]
                return result
        except Exception as exc:
            result["error"] = str(exc)
            return result

    async def complete_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        """请求 DeepSeek 返回 JSON，并产出安全的字典结果。

        所有 Agent 节点都会调用这个方法。它有三层稳定性保护：
        未配置 Key 时直接兜底、重复 prompt 走 Redis 缓存、模型 JSON 异常
        或网络失败时回退到规则结果。
        """

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
            # 第一版优先保证产品 Demo 稳定，而不是把模型传输错误直接暴露给 UI。
            # 后续可以接入日志和可观测性系统。
            return fallback

    async def stream_chat(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        fallback: str,
    ) -> AsyncIterator[str]:
        """以文本流形式请求 DeepSeek 聊天接口。

        前端聊天抽屉需要边生成边展示，因此这里直接解析 DeepSeek 的
        `stream=true` SSE 响应，并把增量文本 chunk 透传给 FastAPI。
        如果没有配置 API Key 或请求失败，就返回本地兜底文本流。
        """

        if not self.settings.deepseek_api_key:
            async for chunk in _fallback_stream(fallback):
                yield chunk
            return

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream(
                    "POST",
                    f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.deepseek_model,
                        "stream": True,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            *messages,
                        ],
                    },
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        delta = payload.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
        except Exception:
            async for chunk in _fallback_stream(fallback):
                yield chunk


def _parse_json_object(content: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """从模型输出中解析 JSON 对象。

    虽然我们要求 DeepSeek 返回 JSON，但模型有时会在 JSON 外包裹解释文字。
    这个函数会尝试从文本中截取 JSON；如果仍然失败，就返回确定性兜底结果。
    """

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


async def _fallback_stream(text: str) -> AsyncIterator[str]:
    """把兜底文本拆成小片段，模拟流式输出体验。"""

    step = 18
    for index in range(0, len(text), step):
        yield text[index : index + step]
