from __future__ import annotations

from sqlalchemy.orm import Session

from app import crud, models
from app.core.config import get_settings
from app.services.chunking import split_text_into_chunks
from app.services.document_parser import extract_text
from app.services.knowledge_base import ChromaKnowledgeBase


def build_material_knowledge_base(
    db: Session, material: models.CourseMaterial
) -> models.CourseMaterial:
    """执行课程资料建库管线。

    这个函数封装“解析文件 -> 切分 chunk -> 写入 Chroma -> 保存 chunk 元数据”
    的完整流程。同步上传接口和 Celery 后台任务都会调用它，避免维护两份逻辑。
    """

    crud.mark_material_processing(db, material)
    settings = get_settings()

    text = extract_text(material.storage_path)
    chunks = split_text_into_chunks(
        text,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    if not chunks:
        raise ValueError("No readable text was extracted from this file.")

    chroma_ids = ChromaKnowledgeBase().upsert_chunks(
        goal_id=material.goal_id,
        material_id=material.id,
        filename=material.filename,
        chunks=chunks,
    )
    return crud.replace_material_chunks(db, material, chunks, chroma_ids)
