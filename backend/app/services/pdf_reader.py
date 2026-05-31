from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

from app import models


def ensure_pdf_material(material: models.CourseMaterial) -> Path:
    """确认资料是可预览的 PDF，并返回本地文件路径。"""

    if material.file_type.lower() != "pdf":
        raise ValueError("当前阅读器第一版只支持 PDF 资料。")
    path = Path(material.storage_path)
    if not path.exists() or not path.is_file():
        raise ValueError("PDF 文件不存在，可能已被移动或删除。")
    return path


def pdf_meta(material: models.CourseMaterial) -> dict:
    """读取 PDF 页数，并统计哪些页面可提取文本。"""

    path = ensure_pdf_material(material)
    readable_pages: list[int] = []
    with fitz.open(path) as document:
        for page_index, page in enumerate(document, start=1):
            if page.get_text("text").strip():
                readable_pages.append(page_index)
        return {
            "material_id": material.id,
            "filename": material.filename,
            "page_count": document.page_count,
            "readable_pages": readable_pages,
        }


def pdf_page_text(material: models.CourseMaterial, page_index: int) -> dict:
    """提取某一页 PDF 文本；图片型页面返回 readable=false。"""

    path = ensure_pdf_material(material)
    with fitz.open(path) as document:
        page = _load_page(document, page_index)
        text = page.get_text("text").strip()
        return {
            "material_id": material.id,
            "filename": material.filename,
            "page_index": page_index,
            "readable": bool(text),
            "text": text,
            "text_hash": hash_text(text),
        }


def render_pdf_page_png(material: models.CourseMaterial, page_index: int, zoom: float = 2) -> bytes:
    """把 PDF 某一页渲染为 PNG，供前端阅读器展示。"""

    path = ensure_pdf_material(material)
    safe_zoom = max(0.8, min(3.0, zoom))
    with fitz.open(path) as document:
        page = _load_page(document, page_index)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(safe_zoom, safe_zoom), alpha=False)
        return pixmap.tobytes("png")


def hash_text(text: str) -> str:
    """为页面文本生成稳定 hash，用于判断翻译缓存是否过期。"""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_page(document: fitz.Document, page_index: int) -> fitz.Page:
    """按 1-based 页码读取页面，并给非法页码抛出明确错误。"""

    if page_index < 1 or page_index > document.page_count:
        raise ValueError("PDF 页码超出范围。")
    return document.load_page(page_index - 1)
