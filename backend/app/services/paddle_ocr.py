from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from app import models
from app.core.config import get_settings


@dataclass
class OcrPage:
    """PaddleOCR 返回后落盘的一页 Markdown 内容。"""

    page_index: int
    markdown: str


@dataclass
class OcrResult:
    """一次 PDF OCR 任务的本地缓存结果。"""

    material_id: int
    provider: str
    model: str
    job_id: str | None
    pages: list[OcrPage]
    cache_dir: Path


class PaddleOcrError(RuntimeError):
    """PaddleOCR 提交、轮询或结果下载失败时抛出的业务异常。"""


def ocr_is_enabled() -> bool:
    """判断当前环境是否启用了 PaddleOCR。"""

    settings = get_settings()
    return settings.ocr_provider.strip().lower() == "paddleocr"


def ocr_cache_dir(material: models.CourseMaterial) -> Path:
    """返回某个素材的 OCR 缓存目录。"""

    settings = get_settings()
    return Path(settings.ocr_storage_dir) / f"material_{material.id}"


def cached_ocr_pages(material: models.CourseMaterial) -> list[OcrPage]:
    """读取已经保存在本地的 OCR Markdown 页面。"""

    pages_dir = ocr_cache_dir(material) / "pages"
    if not pages_dir.exists():
        return []

    pages: list[OcrPage] = []
    for path in sorted(pages_dir.glob("page_*.md")):
        match = re.search(r"page_(\d+)\.md$", path.name)
        if not match:
            continue
        pages.append(
            OcrPage(
                page_index=int(match.group(1)),
                markdown=path.read_text(encoding="utf-8", errors="ignore").strip(),
            )
        )
    return [page for page in pages if page.markdown]


def cached_ocr_page_text(material: models.CourseMaterial, page_index: int) -> str | None:
    """读取某一页的 OCR Markdown；没有缓存时返回 None。"""

    page_path = _page_path(material, page_index)
    if not page_path.exists():
        return None
    text = page_path.read_text(encoding="utf-8", errors="ignore").strip()
    return text or None


def cached_ocr_document_text(material: models.CourseMaterial) -> str:
    """把整份 PDF 的 OCR Markdown 合并为 RAG 建库文本。"""

    parts = [
        f"[PDF OCR page {page.page_index}]\n{page.markdown}"
        for page in cached_ocr_pages(material)
    ]
    return "\n\n".join(parts)


async def ensure_pdf_ocr(material: models.CourseMaterial) -> OcrResult | None:
    """确保 PDF 已经完成 OCR，并把结果保存在本地。

    如果没有启用 PaddleOCR，则返回 None，由调用方回退到 PyMuPDF 文本提取。
    已存在本地缓存时不会重复提交远程任务。
    """

    return await ensure_pdf_ocr_with_progress(material)


async def ensure_pdf_ocr_with_progress(
    material: models.CourseMaterial,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> OcrResult | None:
    """确保 PDF 已经完成 OCR，并在轮询时报告页数进度。"""

    if material.file_type.lower() != "pdf":
        return None

    cached_pages = cached_ocr_pages(material)
    if cached_pages:
        settings = get_settings()
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "ocr_cached",
                    "message": f"OCR 缓存命中：{material.filename}",
                    "current_file": material.filename,
                    "current_page": len(cached_pages),
                    "total_pages": len(cached_pages),
                }
            )
        return OcrResult(
            material_id=material.id,
            provider="paddleocr",
            model=settings.paddle_ocr_model,
            job_id=_read_cached_job_id(material),
            pages=cached_pages,
            cache_dir=ocr_cache_dir(material),
        )

    if not ocr_is_enabled():
        return None

    settings = get_settings()
    if not settings.paddle_ocr_token.strip():
        raise PaddleOcrError("PADDLE_OCR_TOKEN is not configured in backend/.env.")

    file_path = Path(material.storage_path)
    if not file_path.exists():
        raise PaddleOcrError(f"Material file not found: {material.storage_path}")

    cache_dir = ocr_cache_dir(material)
    cache_dir.mkdir(parents=True, exist_ok=True)
    _write_meta(
        material,
        {
            "provider": "paddleocr",
            "model": settings.paddle_ocr_model,
            "state": "submitting",
            "file_sha256": _hash_file(file_path),
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    async with httpx.AsyncClient(timeout=120) as client:
        job_id = await _submit_job(client, file_path)
        job_payload = await _poll_job(
            client,
            job_id,
            material.filename,
            progress_callback=progress_callback,
        )
        jsonl_url = job_payload["data"]["resultUrl"]["jsonUrl"]
        jsonl_text = await _download_text(client, jsonl_url)
        pages = await _save_jsonl_result(client, material, job_id, jsonl_text)

    return OcrResult(
        material_id=material.id,
        provider="paddleocr",
        model=settings.paddle_ocr_model,
        job_id=job_id,
        pages=pages,
        cache_dir=cache_dir,
    )


async def _submit_job(client: httpx.AsyncClient, file_path: Path) -> str:
    """上传本地 PDF 文件并提交 PaddleOCR 任务。"""

    settings = get_settings()
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }
    headers = {"Authorization": f"bearer {settings.paddle_ocr_token}"}
    data = {
        "model": settings.paddle_ocr_model,
        "optionalPayload": json.dumps(optional_payload, ensure_ascii=False),
    }

    with file_path.open("rb") as file_obj:
        response = await client.post(
            settings.paddle_ocr_job_url,
            headers=headers,
            data=data,
            files={"file": (file_path.name, file_obj, "application/pdf")},
        )
    if response.status_code != 200:
        raise PaddleOcrError(
            f"PaddleOCR job submit failed: {response.status_code} {response.text[:500]}"
        )

    payload = response.json()
    try:
        return payload["data"]["jobId"]
    except KeyError as exc:
        raise PaddleOcrError(f"PaddleOCR job response missing jobId: {payload}") from exc


async def _poll_job(
    client: httpx.AsyncClient,
    job_id: str,
    filename: str,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """轮询 PaddleOCR 任务直到 done 或 failed。"""

    settings = get_settings()
    headers = {"Authorization": f"bearer {settings.paddle_ocr_token}"}
    deadline = asyncio.get_running_loop().time() + settings.ocr_poll_timeout_seconds
    last_payload: dict[str, Any] | None = None

    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"{settings.paddle_ocr_job_url}/{job_id}", headers=headers)
        if response.status_code != 200:
            raise PaddleOcrError(
                f"PaddleOCR job poll failed: {response.status_code} {response.text[:500]}"
            )

        payload = response.json()
        last_payload = payload
        data = payload.get("data", {})
        state = data.get("state")
        if state == "done":
            extract_progress = data.get("extractProgress") or {}
            if progress_callback is not None:
                progress_callback(
                    {
                        "stage": "ocr_done",
                        "message": f"OCR 完成：{filename}",
                        "current_file": filename,
                        "current_page": extract_progress.get("extractedPages"),
                        "total_pages": extract_progress.get("totalPages"),
                    }
                )
            return payload
        if state == "failed":
            raise PaddleOcrError(data.get("errorMsg") or "PaddleOCR job failed.")

        if progress_callback is not None:
            extract_progress = data.get("extractProgress") or {}
            progress_callback(
                {
                    "stage": "ocr_running",
                    "message": f"正在 OCR：{filename}",
                    "current_file": filename,
                    "current_page": extract_progress.get("extractedPages"),
                    "total_pages": extract_progress.get("totalPages"),
                    "state": state,
                }
            )

        await asyncio.sleep(settings.ocr_poll_interval_seconds)

    raise PaddleOcrError(f"PaddleOCR job timed out. Last response: {last_payload}")


async def _download_text(client: httpx.AsyncClient, url: str) -> str:
    """下载 PaddleOCR 生成的 JSONL 结果。"""

    response = await client.get(url)
    response.raise_for_status()
    return response.text


async def _save_jsonl_result(
    client: httpx.AsyncClient,
    material: models.CourseMaterial,
    job_id: str,
    jsonl_text: str,
) -> list[OcrPage]:
    """把 JSONL 解析为分页 Markdown，并下载结果中的图片到本地。"""

    settings = get_settings()
    cache_dir = ocr_cache_dir(material)
    pages_dir = cache_dir / "pages"
    images_dir = cache_dir / "images"
    pages_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "result.jsonl").write_text(jsonl_text, encoding="utf-8")

    pages: list[OcrPage] = []
    page_index = 1
    for line in jsonl_text.splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        result = payload.get("result", {})
        for item in result.get("layoutParsingResults", []):
            markdown = item.get("markdown", {}).get("text", "").strip()
            if markdown:
                _page_path(material, page_index).write_text(markdown, encoding="utf-8")
                pages.append(OcrPage(page_index=page_index, markdown=markdown))

            await _download_markdown_images(
                client,
                images_dir,
                page_index,
                item.get("markdown", {}).get("images", {}),
            )
            await _download_output_images(
                client,
                images_dir,
                page_index,
                item.get("outputImages", {}),
            )
            page_index += 1

    _write_meta(
        material,
        {
            "provider": "paddleocr",
            "model": settings.paddle_ocr_model,
            "job_id": job_id,
            "state": "done",
            "page_count": len(pages),
            "updated_at": datetime.utcnow().isoformat(),
        },
    )
    if not pages:
        raise PaddleOcrError("PaddleOCR finished but no Markdown pages were extracted.")
    return pages


async def _download_markdown_images(
    client: httpx.AsyncClient,
    images_dir: Path,
    page_index: int,
    images: dict[str, str],
) -> None:
    """下载 Markdown 内引用的图片。"""

    for image_path, image_url in images.items():
        safe_name = _safe_relative_image_name(image_path)
        target = images_dir / f"page_{page_index:03d}" / safe_name
        await _download_image(client, image_url, target)


async def _download_output_images(
    client: httpx.AsyncClient,
    images_dir: Path,
    page_index: int,
    images: dict[str, str],
) -> None:
    """下载 PaddleOCR 额外输出的版面图、表格图等。"""

    for image_name, image_url in images.items():
        suffix = Path(urlparse(image_url).path).suffix or ".jpg"
        target = images_dir / f"{_safe_name(image_name)}_{page_index:03d}{suffix}"
        await _download_image(client, image_url, target)


async def _download_image(client: httpx.AsyncClient, url: str, target: Path) -> None:
    """下载单张图片；失败不影响 OCR Markdown 主流程。"""

    if not url:
        return
    try:
        response = await client.get(url)
        if response.status_code != 200:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
    except httpx.HTTPError:
        return


def _page_path(material: models.CourseMaterial, page_index: int) -> Path:
    return ocr_cache_dir(material) / "pages" / f"page_{page_index:03d}.md"


def _write_meta(material: models.CourseMaterial, payload: dict[str, Any]) -> None:
    meta_path = ocr_cache_dir(material) / "meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_cached_job_id(material: models.CourseMaterial) -> str | None:
    meta_path = ocr_cache_dir(material) / "meta.json"
    if not meta_path.exists():
        return None
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    job_id = payload.get("job_id")
    return job_id if isinstance(job_id, str) else None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for block in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative_image_name(name: str) -> Path:
    parts = [_safe_name(part) for part in Path(name).parts if part not in {"", ".", ".."}]
    return Path(*parts) if parts else Path("image.jpg")


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("._")
    return cleaned or "image"
