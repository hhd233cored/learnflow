from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import get_settings
from app.services.document_parser import SUPPORTED_EXTENSIONS


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
