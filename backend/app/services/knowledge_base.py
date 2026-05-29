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
    ) -> list[str]:
        """插入或替换某个上传资料的 chunk。

        Chroma 保存用于检索的文本和向量。英文资料会写入“原文 + 中文摘要
        + 中英术语”的增强文本，让中文查询也更容易召回英文教材片段。
        返回的 ids 会写入 SQL，让关系型数据库能够引用 Chroma 中的文档。
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
                    "source": f"{filename}#chunk-{index}",
                },
                enrichments,
                index,
            )
            for index in range(len(chunks))
        ]
        if documents:
            collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return ids

    def query(self, goal_id: int, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """检索某个目标的 Chroma collection，并规范化返回结果。"""

        collection_name = collection_name_for_goal(goal_id)
        collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"},
        )
        result = collection.query(
            query_texts=[query],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
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
        """删除某个学习目标对应的 Chroma collection。

        删除学习计划时调用。Chroma collection 不存在或删除失败时不抛出，
        因为关系型数据库删除才是用户可见的主流程。
        """

        try:
            self.client.delete_collection(collection_name_for_goal(goal_id))
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

    if not enrichments or index >= len(enrichments):
        return base

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
    return base


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
