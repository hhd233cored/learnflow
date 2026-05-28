from __future__ import annotations

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
    ) -> list[str]:
        """插入或替换某个上传资料的 chunk。

        Chroma 保存完整 chunk 文本和向量。返回的 ids 会写入 SQL，
        让关系型数据库能够引用 Chroma 中的文档。
        """

        collection_name = collection_name_for_goal(goal_id)
        collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"},
        )
        ids = [f"material_{material_id}_chunk_{index}" for index in range(len(chunks))]
        metadatas = [
            {
                "goal_id": goal_id,
                "material_id": material_id,
                "chunk_index": index,
                "filename": filename,
                "source": f"{filename}#chunk-{index}",
            }
            for index in range(len(chunks))
        ]
        if chunks:
            collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
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
            hits.append(
                {
                    "content": document,
                    "metadata": metadatas[index] if index < len(metadatas) else {},
                    "distance": distances[index] if index < len(distances) else None,
                }
            )
        return hits
