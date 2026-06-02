from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chromadb

from app.core.config import get_settings
from app.services.embeddings import HashEmbeddingFunction


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
        self.embedding_function = HashEmbeddingFunction()

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
        query_args: dict[str, Any] = {
            "query_texts": [query],
            "n_results": top_k,
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
                }
            )
        return hits

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
    return decoded
