from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import chromadb
from sqlalchemy import select

from app import models
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.embeddings import get_embedding_function
from app.services.query_rewrite import QueryPlan, formula_tokens, rewrite_query, tokenize_for_lexical
from app.services.rerankers import get_reranker


_LEXICAL_TOKEN_CACHE: dict[tuple[int, str], list[str]] = {}


def collection_name_for_goal(goal_id: int) -> str:
    """返回某个学习目标对应的 Chroma collection 名称。"""

    return f"goal_{goal_id}_knowledge"


class ChromaKnowledgeBase:
    """对 Chroma 本地持久化 collection 的轻量封装。"""

    def __init__(self) -> None:
        """初始化本地持久化 Chroma 客户端和 embedding 函数。"""

        settings = get_settings()
        Path(settings.chroma_persist_dir).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        self.embedding_function = get_embedding_function(
            settings.embedding_provider,
            settings.embedding_model,
            settings.embedding_device,
            settings.embedding_batch_size,
            settings.embedding_use_fp16,
            settings.hf_api_token,
        )
        self.reranker = get_reranker(
            settings.reranker_provider,
            settings.reranker_model,
            settings.reranker_device,
            settings.reranker_batch_size,
            settings.reranker_use_fp16,
        )
        self.reranker_candidate_count = max(
            settings.reranker_candidate_count,
            1,
        )
        self.hybrid_search_enabled = settings.rag_hybrid_search_enabled
        self.lexical_candidate_count = max(settings.rag_lexical_candidate_count, 1)

    def upsert_chunks(
        self,
        goal_id: int,
        material_id: int,
        filename: str,
        chunks: list[str],
        enrichments: list[dict[str, Any]] | None = None,
        chunk_metadatas: list[dict[str, Any]] | None = None,
        plan_id: int | None = None,
        day_index: int | None = None,
        source_type: str = "material",
    ) -> list[str]:
        """插入或替换某个素材的 chunk。

        RAG 存储仍然采用“一个学习目标一个 collection”的结构，plan/day/material
        都作为 metadata 写入。这样既能避免重复建库，又能在检索时按素材或 Day 过滤。
        """

        collection_name = collection_name_for_goal(goal_id)
        collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"},
        )
        ids = [f"material_{material_id}_chunk_{index}" for index in range(len(chunks))]
        documents = [
            _document_for_embedding(chunks[index], enrichments, index)
            for index in range(len(chunks))
        ]
        metadatas = [
            _metadata_for_chunk(
                {
                    "goal_id": goal_id,
                    "material_id": material_id,
                    "chunk_index": index,
                    "filename": filename,
                    "source": _chunk_source(filename, index, chunk_metadatas),
                    "source_name": filename,
                    "source_type": source_type,
                    "plan_id": plan_id,
                    "day_index": day_index,
                    **_chunk_metadata(chunk_metadatas, index),
                },
                enrichments,
                index,
            )
            for index in range(len(chunks))
        ]
        if documents:
            collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return ids

    def query(
        self,
        goal_id: int,
        query: str,
        top_k: int = 5,
        material_id: int | None = None,
        plan_id: int | None = None,
        day_index: int | None = None,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """检索某个目标的 Chroma collection，并规范化返回结果。"""

        collection_name = collection_name_for_goal(goal_id)
        collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"},
        )
        query_plan = rewrite_query(query)
        candidate_count = max(top_k, self.reranker_candidate_count)
        if self.hybrid_search_enabled:
            candidate_count = max(candidate_count, self.lexical_candidate_count)
        n_results = candidate_count if self.reranker or self.hybrid_search_enabled else top_k
        query_args: dict[str, Any] = {
            "query_texts": [query_plan.semantic_query],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        where_filter = _where_filter(
            material_id=material_id,
            plan_id=plan_id,
            day_index=day_index,
            source_type=source_type,
        )
        if where_filter:
            query_args["where"] = where_filter

        result = collection.query(**query_args)
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        hits = []
        for index, document in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) else {}
            hits.append(
                {
                    "content": document,
                    "metadata": _decode_metadata(metadata),
                    "distance": distances[index] if index < len(distances) else None,
                    "retrieval_source": "dense",
                }
            )
        if self.hybrid_search_enabled:
            hits = _merge_hits(
                hits,
                _lexical_hits(
                    goal_id=goal_id,
                    query_plan=query_plan,
                    limit=self.lexical_candidate_count,
                    material_id=material_id,
                    plan_id=plan_id,
                    day_index=day_index,
                    source_type=source_type,
                ),
            )
        if self.reranker:
            return self.reranker.rerank(query_plan.semantic_query, hits, top_k)
        hits.sort(key=_hybrid_sort_score, reverse=True)
        return hits[:top_k]

    def delete_goal_collection(self, goal_id: int) -> None:
        """删除某个学习目标对应的 Chroma collection。"""

        try:
            self.client.delete_collection(collection_name_for_goal(goal_id))
        except Exception:
            return

    def delete_material_documents(self, goal_id: int, material_id: int) -> None:
        """删除某个素材写入 Chroma 的所有 document。"""

        try:
            collection = self.client.get_collection(
                name=collection_name_for_goal(goal_id),
                embedding_function=self.embedding_function,
            )
            collection.delete(where={"material_id": material_id})
        except Exception:
            return


def _lexical_hits(
    goal_id: int,
    query_plan: QueryPlan,
    limit: int,
    material_id: int | None = None,
    plan_id: int | None = None,
    day_index: int | None = None,
    source_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return lightweight lexical candidates from persisted chunk text."""

    if plan_id is not None or day_index is not None or source_type:
        return []
    terms = query_plan.lexical_terms
    formula_terms_set = set(query_plan.formula_terms)
    if not terms and not formula_terms_set:
        return []

    db = SessionLocal()
    try:
        stmt = (
            select(models.DocumentChunk, models.CourseMaterial)
            .join(models.CourseMaterial)
            .where(models.CourseMaterial.goal_id == goal_id)
        )
        if material_id is not None:
            stmt = stmt.where(models.DocumentChunk.material_id == material_id)
        rows = list(db.execute(stmt).all())
    finally:
        db.close()

    if not rows:
        return []

    prepared: list[tuple[models.DocumentChunk, models.CourseMaterial, list[str]]] = []
    doc_freq: Counter[str] = Counter()
    for chunk, material in rows:
        tokens = _chunk_tokens(chunk)
        prepared.append((chunk, material, tokens))
        doc_freq.update(set(tokens))

    avg_len = sum(len(tokens) for _, _, tokens in prepared) / max(len(prepared), 1)
    hits: list[dict[str, Any]] = []
    for chunk, material, tokens in prepared:
        score = _bm25_score(terms, tokens, doc_freq, len(prepared), avg_len)
        formulas = _safe_list(chunk.formulas)
        if formula_terms_set and formulas:
            formula_text = " ".join(str(item) for item in formulas)
            matched = formula_terms_set.intersection(formula_tokens(formula_text, formulas))
            score += min(len(matched) * 1.2, 4.8)
        if score <= 0:
            continue
        hits.append(_hit_from_chunk(chunk, material, score))

    hits.sort(key=lambda item: item.get("lexical_score", 0.0), reverse=True)
    return hits[:limit]


def _chunk_tokens(chunk: models.DocumentChunk) -> list[str]:
    cache_key = (
        chunk.id,
        chunk.updated_at.isoformat() if chunk.updated_at else "",
    )
    cached = _LEXICAL_TOKEN_CACHE.get(cache_key)
    if cached is not None:
        return cached
    tokens = tokenize_for_lexical(
        " ".join(
            [
                chunk.retrieval_text or "",
                chunk.content_preview or "",
                " ".join(_term_texts(chunk.key_terms)),
                " ".join(str(item) for item in _safe_list(chunk.formulas)),
            ]
        )
    )
    if len(_LEXICAL_TOKEN_CACHE) > 10000:
        _LEXICAL_TOKEN_CACHE.clear()
    _LEXICAL_TOKEN_CACHE[cache_key] = tokens
    return tokens


def _term_texts(value: Any) -> list[str]:
    terms = []
    for item in _safe_list(value):
        if isinstance(item, dict):
            terms.extend(str(item.get(key) or "") for key in ("source", "zh"))
        else:
            terms.append(str(item))
    return [term for term in terms if term.strip()]


def _bm25_score(
    query_terms: list[str],
    doc_terms: list[str],
    doc_freq: Counter[str],
    total_docs: int,
    avg_len: float,
) -> float:
    if not query_terms or not doc_terms:
        return 0.0
    counts = Counter(doc_terms)
    doc_len = len(doc_terms)
    k1 = 1.4
    b = 0.75
    score = 0.0
    for term in query_terms:
        freq = counts.get(term, 0)
        if freq <= 0:
            continue
        df = doc_freq.get(term, 0)
        idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
        denom = freq + k1 * (1 - b + b * doc_len / max(avg_len, 1.0))
        score += idf * (freq * (k1 + 1)) / denom
    return float(score)


def _hit_from_chunk(
    chunk: models.DocumentChunk, material: models.CourseMaterial, score: float
) -> dict[str, Any]:
    return {
        "content": chunk.content_raw or chunk.retrieval_text or chunk.content_preview,
        "metadata": {
            "goal_id": material.goal_id,
            "material_id": material.id,
            "chunk_index": chunk.chunk_index,
            "filename": material.filename,
            "source": f"{material.filename}#chunk-{chunk.chunk_index}",
            "source_name": material.filename,
            "source_type": material.file_type,
            "key_terms": _safe_list(chunk.key_terms),
            "formulas": _safe_list(chunk.formulas),
        },
        "distance": None,
        "lexical_score": score,
        "retrieval_source": "lexical",
    }


def _merge_hits(
    dense_hits: list[dict[str, Any]], lexical_hits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for hit in [*dense_hits, *lexical_hits]:
        key = _hit_key(hit)
        if key not in merged:
            merged[key] = dict(hit)
            continue
        existing = merged[key]
        if hit.get("lexical_score") is not None:
            existing["lexical_score"] = max(
                float(existing.get("lexical_score") or 0.0),
                float(hit.get("lexical_score") or 0.0),
            )
        if existing.get("distance") is None:
            existing["distance"] = hit.get("distance")
        existing["retrieval_source"] = "hybrid"
        existing["metadata"] = {
            **(existing.get("metadata") or {}),
            **(hit.get("metadata") or {}),
        }
    return list(merged.values())


def _hit_key(hit: dict[str, Any]) -> str:
    metadata = hit.get("metadata") or {}
    return f"{metadata.get('material_id', 'unknown')}:{metadata.get('chunk_index', 'unknown')}"


def _hybrid_sort_score(hit: dict[str, Any]) -> float:
    distance = hit.get("distance")
    dense_score = 0.0 if distance is None else 1.0 / (1.0 + max(float(distance), 0.0))
    lexical_score = min(float(hit.get("lexical_score") or 0.0), 8.0) / 8.0
    return dense_score * 0.7 + lexical_score * 0.3


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _document_for_embedding(
    raw_chunk: str, enrichments: list[dict[str, Any]] | None, index: int
) -> str:
    """取出写入 Chroma 的检索文本。"""

    if not enrichments or index >= len(enrichments):
        return raw_chunk
    return str(enrichments[index].get("embedding_text") or raw_chunk)


def _metadata_for_chunk(
    base: dict[str, Any], enrichments: list[dict[str, Any]] | None, index: int
) -> dict[str, Any]:
    """把增强信息压平成 Chroma 可接受的 metadata。"""

    if enrichments and index < len(enrichments):
        item = enrichments[index]
        base.update(
            {
                "source_lang": str(item.get("source_lang") or "unknown"),
                "summary_zh": str(item.get("summary_zh") or ""),
                "key_terms_json": json.dumps(
                    item.get("key_terms") or [], ensure_ascii=False, default=str
                ),
                "formulas_json": json.dumps(
                    item.get("formulas") or [], ensure_ascii=False, default=str
                ),
            }
        )
    return _compact_metadata(base)


def _chunk_metadata(
    chunk_metadatas: list[dict[str, Any]] | None, index: int
) -> dict[str, Any]:
    """返回某个 chunk 额外 metadata，例如 OCR 页码。"""

    if not chunk_metadatas or index >= len(chunk_metadatas):
        return {}
    return dict(chunk_metadatas[index])


def _chunk_source(
    filename: str, index: int, chunk_metadatas: list[dict[str, Any]] | None
) -> str:
    """生成可读的 chunk 来源标识。"""

    metadata = _chunk_metadata(chunk_metadatas, index)
    page_index = metadata.get("page_index")
    if page_index is not None:
        return f"{filename}#page-{page_index}-chunk-{index}"
    return f"{filename}#chunk-{index}"


def _compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """移除 Chroma 不接受的空值，并只保留标量 metadata。"""

    compacted: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            compacted[key] = value
    return compacted


def _where_filter(
    material_id: int | None = None,
    plan_id: int | None = None,
    day_index: int | None = None,
    source_type: str | None = None,
) -> dict[str, Any] | None:
    """把前端筛选项转换为 Chroma where 查询条件。"""

    conditions: list[dict[str, Any]] = []
    if material_id is not None:
        conditions.append({"material_id": material_id})
    if plan_id is not None:
        conditions.append({"plan_id": plan_id})
    if day_index is not None:
        conditions.append({"day_index": day_index})
    if source_type:
        conditions.append({"source_type": source_type})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _decode_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """把 Chroma metadata 中的 JSON 字符串恢复成前端/Agent 更容易使用的结构。"""

    decoded = dict(metadata)
    raw_terms = decoded.get("key_terms_json")
    if isinstance(raw_terms, str):
        try:
            decoded["key_terms"] = json.loads(raw_terms)
        except json.JSONDecodeError:
            decoded["key_terms"] = []
    raw_formulas = decoded.get("formulas_json")
    if isinstance(raw_formulas, str):
        try:
            decoded["formulas"] = json.loads(raw_formulas)
        except json.JSONDecodeError:
            decoded["formulas"] = []
    return decoded
