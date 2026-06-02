from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app import models
from app.core.config import get_settings
from app.services.document_parser import SUPPORTED_EXTENSIONS
from app.services.paddle_ocr import ocr_cache_dir


def save_upload_file(upload: UploadFile, goal_id: int) -> tuple[str, str, str]:
    """把上传的课程资料保存到配置的存储目录。

    返回保存路径、原始文件名和标准化后的文件类型。实际保存文件名会随机化，
    用来避免文件名冲突和路径穿越问题。
    """

    settings = get_settings()
    original_name = Path(upload.filename or "material").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            "Unsupported file type. Please upload PDF, DOCX, PPTX, TXT, or MD."
        )

    goal_dir = Path(settings.material_upload_dir) / f"goal_{goal_id}"
    goal_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}{suffix}"
    target = goal_dir / stored_name

    with target.open("wb") as buffer:
        shutil.copyfileobj(upload.file, buffer)

    return str(target), original_name, suffix.lstrip(".")


def delete_material_files(material: models.CourseMaterial) -> None:
    """删除素材原始文件和对应的本地 OCR 缓存。"""

    storage_path = material.storage_path or ""
    if not storage_path.startswith("manual://"):
        path = Path(storage_path)
        if path.exists() and path.is_file():
            path.unlink()
        parent = path.parent
        if parent.exists() and parent.is_dir():
            try:
                parent.rmdir()
            except OSError:
                pass

    cache_dir = ocr_cache_dir(material)
    if cache_dir.exists() and cache_dir.is_dir():
        shutil.rmtree(cache_dir)
