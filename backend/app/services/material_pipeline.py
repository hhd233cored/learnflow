from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app import crud, models
from app.core.config import get_settings
from app.services.chunking import split_text_into_chunks
from app.services.document_enrichment import enrich_chunks
from app.services.document_parser import extract_text
from app.services.knowledge_base import ChromaKnowledgeBase
from app.services.paddle_ocr import cached_ocr_document_text, ensure_pdf_ocr_with_progress


async def build_material_knowledge_base(
    db: Session,
    material: models.CourseMaterial,
    plan_id: int | None = None,
    day_index: int | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> models.CourseMaterial:
    """执行课程资料建库管线。

    这个函数封装“解析文件 -> 切分 chunk -> 中英增强 -> 写入 Chroma
    -> 保存 chunk 元数据”的完整流程。同步上传接口和 Celery 后台任务都会
    调用它，避免维护两份逻辑。
    """

    crud.mark_material_processing(db, material)
    settings = get_settings()

    source_type = material.file_type
    chunk_metadatas: list[dict] | None = None
    text = ""

    if material.file_type.lower() == "pdf":
        _report(progress_callback, "ocr_prepare", {"message": f"准备 OCR：{material.filename}"})
        ocr_result = await ensure_pdf_ocr_with_progress(
            material,
            progress_callback=lambda payload: _report(progress_callback, "ocr_running", payload),
        )
        if ocr_result is not None:
            source_type = "ocr"
            chunks = []
            chunk_metadatas = []
            _report(
                progress_callback,
                "chunking",
                {"message": f"正在切分 OCR Markdown：{material.filename}"},
            )
            for page in ocr_result.pages:
                page_chunks = split_text_into_chunks(
                    page.markdown,
                    chunk_size=settings.chunk_size,
                    chunk_overlap=settings.chunk_overlap,
                )
                chunks.extend(page_chunks)
                chunk_metadatas.extend(
                    {
                        "page_index": page.page_index,
                        "ocr_provider": ocr_result.provider,
                        "ocr_model": ocr_result.model,
                    }
                    for _ in page_chunks
                )
        else:
            _report(
                progress_callback,
                "parsing",
                {"message": f"未启用 OCR，正在提取 PDF 内置文本：{material.filename}"},
            )
            text = extract_text(material.storage_path)
            chunks = split_text_into_chunks(
                text,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )
    else:
        _report(
            progress_callback,
            "parsing",
            {"message": f"正在解析资料：{material.filename}"},
        )
        text = extract_text(material.storage_path)
        chunks = split_text_into_chunks(
            text,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

    if not text and source_type == "ocr":
        text = cached_ocr_document_text(material)
    if not chunks:
        raise ValueError("No readable text was extracted from this file.")

    _report(
        progress_callback,
        "enriching",
        {"message": f"正在生成 chunk 摘要与关键词：{material.filename}", "chunk_count": len(chunks)},
    )
    enriched_chunks = await enrich_chunks(chunks, material.filename)
    _report(
        progress_callback,
        "indexing",
        {"message": f"正在写入 Chroma 知识库：{material.filename}", "chunk_count": len(chunks)},
    )
    chroma_ids = ChromaKnowledgeBase().upsert_chunks(
        goal_id=material.goal_id,
        material_id=material.id,
        filename=material.filename,
        chunks=chunks,
        enrichments=enriched_chunks,
        chunk_metadatas=chunk_metadatas,
        plan_id=plan_id,
        day_index=day_index,
        source_type=source_type,
    )
    material = crud.replace_material_chunks(db, material, chunks, chroma_ids)
    _report(
        progress_callback,
        "rag_ready",
        {"message": f"知识库构建完成：{material.filename}", "chunk_count": len(chunks)},
    )
    return material


def _report(
    callback: Callable[[str, dict[str, Any]], None] | None,
    stage: str,
    payload: dict[str, Any],
) -> None:
    """向可选的后台任务进度回调报告阶段信息。"""

    if callback is not None:
        callback(stage, payload)
