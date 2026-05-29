from __future__ import annotations

import re
from typing import Any, TypedDict

from app.agents.llm import DeepSeekClient
from app.core.config import get_settings


class EnrichedChunk(TypedDict):
    """增强后的文档 chunk。

    `content` 保留原文，`embedding_text` 用于写入 Chroma 检索。
    对英文资料来说，embedding_text 会包含原文、中文摘要和中英术语，
    从而提升中文查询命中英文教材片段的概率。
    """

    content: str
    embedding_text: str
    source_lang: str
    summary_zh: str
    key_terms: list[dict[str, str]]


async def enrich_chunks(chunks: list[str], filename: str) -> list[EnrichedChunk]:
    """批量增强文档 chunk。

    有 DeepSeek API Key 时，前若干个 chunk 会调用模型生成更准确的中文摘要
    和术语表；未配置 Key 或模型失败时，使用本地启发式规则兜底。
    """

    settings = get_settings()
    llm = DeepSeekClient()
    enriched: list[EnrichedChunk] = []

    for index, chunk in enumerate(chunks):
        fallback = _fallback_enrichment(chunk)

        if settings.deepseek_api_key and index < settings.rag_enrich_max_chunks:
            result = await llm.complete_json(
                system_prompt=(
                    "你是课程资料 RAG 预处理助手。请分析一个课程文档片段，"
                    "识别语言，生成中文摘要，并抽取中英术语对。必须返回 JSON。"
                ),
                user_payload={
                    "filename": filename,
                    "chunk_index": index,
                    "content": chunk[:4000],
                    "schema": {
                        "source_lang": "en|zh|mixed|unknown",
                        "summary_zh": "用中文概括这个片段的核心内容",
                        "key_terms": [
                            {"source": "process scheduling", "zh": "进程调度"}
                        ],
                    },
                },
                fallback=fallback,
            )
            normalized = _normalize_enrichment(chunk, result, fallback)
        else:
            normalized = _normalize_enrichment(chunk, fallback, fallback)

        enriched.append(normalized)

    return enriched


def _fallback_enrichment(content: str) -> dict[str, Any]:
    """在没有 LLM 时生成稳定的 chunk 增强信息。"""

    source_lang = detect_language(content)
    terms = _extract_terms(content)
    if source_lang == "en":
        term_text = "、".join(term["source"] for term in terms[:5]) or "核心概念"
        summary = f"该英文片段主要围绕 {term_text} 等概念展开。"
    elif source_lang == "zh":
        summary = _shorten_zh(content)
    else:
        summary = _shorten_zh(content)
    return {
        "source_lang": source_lang,
        "summary_zh": summary,
        "key_terms": terms,
    }


def _normalize_enrichment(
    content: str, raw: dict[str, Any], fallback: dict[str, Any]
) -> EnrichedChunk:
    """校验模型输出，并生成最终写入 Chroma 的增强文本。"""

    source_lang = str(raw.get("source_lang") or fallback["source_lang"])[:20]
    summary_zh = str(raw.get("summary_zh") or fallback["summary_zh"]).strip()
    key_terms = _normalize_terms(raw.get("key_terms"), fallback["key_terms"])
    term_lines = [
        f"{item['source']} = {item['zh']}"
        for item in key_terms
        if item.get("source") or item.get("zh")
    ]

    embedding_text = "\n".join(
        item
        for item in [
            content,
            f"中文摘要：{summary_zh}" if summary_zh else "",
            "核心术语：" + "；".join(term_lines) if term_lines else "",
        ]
        if item
    )

    return {
        "content": content,
        "embedding_text": embedding_text,
        "source_lang": source_lang,
        "summary_zh": summary_zh,
        "key_terms": key_terms,
    }


def detect_language(text: str) -> str:
    """用字符比例粗略判断 chunk 语言。"""

    english_letters = len(re.findall(r"[A-Za-z]", text))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    if english_letters == 0 and chinese_chars == 0:
        return "unknown"
    if english_letters > chinese_chars * 2:
        return "en"
    if chinese_chars > english_letters:
        return "zh"
    return "mixed"


def _extract_terms(text: str) -> list[dict[str, str]]:
    """从文本里抽取少量候选术语，作为无 LLM 时的兜底术语表。"""

    terms: list[dict[str, str]] = []
    english_terms = re.findall(r"\b[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,2}\b", text)
    for term in english_terms:
        cleaned = term.strip()
        if len(cleaned) < 4:
            continue
        if cleaned.lower() in {"this", "that", "with", "from", "there", "which"}:
            continue
        if cleaned not in [item["source"] for item in terms]:
            terms.append({"source": cleaned[:80], "zh": ""})
        if len(terms) >= 8:
            break

    chinese_terms = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    for term in chinese_terms:
        if term not in [item["zh"] for item in terms]:
            terms.append({"source": term, "zh": term})
        if len(terms) >= 10:
            break
    return terms


def _normalize_terms(value: Any, fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    """把模型返回的术语表规整成短列表。"""

    if not isinstance(value, list):
        return fallback[:10]

    normalized: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            source = str(item.get("source") or item.get("en") or "").strip()
            zh = str(item.get("zh") or item.get("translation") or "").strip()
        else:
            source = str(item).strip()
            zh = ""
        if not source and not zh:
            continue
        normalized.append({"source": source[:80], "zh": zh[:80]})
        if len(normalized) >= 10:
            break
    return normalized or fallback[:10]


def _shorten_zh(text: str) -> str:
    """截取一段适合作为中文摘要兜底的文本。"""

    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= 160:
        return cleaned
    return cleaned[:160] + "..."
