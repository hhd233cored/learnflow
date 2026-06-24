from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz

from app import models
from app.agents.llm import DeepSeekClient


MAX_OUTLINE_ITEMS = 80


@dataclass
class OutlineResult:
    items: list[dict[str, Any]]
    status: str
    source: str


async def extract_material_outline(
    material: models.CourseMaterial,
    *,
    document_text: str = "",
    ocr_pages: list[Any] | None = None,
    refine_with_llm: bool = False,
) -> OutlineResult:
    """Extract a lightweight course outline for planner context."""

    result = _extract_outline_local(material, document_text=document_text, ocr_pages=ocr_pages)
    llm = DeepSeekClient()
    if refine_with_llm and result.items and llm.settings.deepseek_api_key:
        refined = await _refine_outline_with_llm(result.items, material.filename)
        if refined:
            return OutlineResult(items=refined, status="ready", source="llm_refined")
    return result


def _extract_outline_local(
    material: models.CourseMaterial,
    *,
    document_text: str = "",
    ocr_pages: list[Any] | None = None,
) -> OutlineResult:
    if material.file_type.lower() == "pdf":
        toc_items = _extract_pdf_toc(Path(material.storage_path))
        if toc_items:
            return OutlineResult(items=toc_items, status="ready", source="pdf_toc")

    text_items = _extract_text_toc(_front_document_text(document_text))
    if text_items:
        return OutlineResult(items=text_items, status="ready", source="text_toc")

    ocr_text = _ocr_pages_text(ocr_pages, max_pages=20)
    text_items = _extract_text_toc(ocr_text)
    if text_items:
        return OutlineResult(items=text_items, status="ready", source="ocr_markdown")

    return OutlineResult(items=[], status="unavailable", source="heading_infer")


def _extract_pdf_toc(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with fitz.open(path) as doc:
            raw_toc = doc.get_toc(simple=True)
    except Exception:
        return []

    items: list[dict[str, Any]] = []
    for order, entry in enumerate(raw_toc, start=1):
        if len(entry) < 3:
            continue
        level, title, page = entry[:3]
        title = _clean_title(str(title))
        if not _valid_title(title):
            continue
        items.append(
            {
                "title": title,
                "level": _clamp_level(level),
                "page_start": _positive_int(page),
                "page_end": None,
                "order": len(items) + 1,
                "confidence": 0.95,
                "source": "pdf_toc",
            }
        )
        if len(items) >= MAX_OUTLINE_ITEMS:
            break
    return _with_page_ends(items)


def _extract_text_toc(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    lines = _candidate_lines(text, max_lines=900)
    items: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    toc_window_started = False

    for raw_line in lines:
        line = _normalize_spaces(raw_line)
        if not line:
            continue
        if _looks_like_toc_header(line):
            toc_window_started = True
            continue
        match = _match_toc_line(line)
        if match is None:
            continue
        title, level, page = match
        title = _clean_title(title)
        if not _valid_title(title) or title in seen_titles:
            continue
        seen_titles.add(title)
        confidence = 0.86 if toc_window_started or page else 0.72
        items.append(
            {
                "title": title,
                "level": level,
                "page_start": page,
                "page_end": None,
                "order": len(items) + 1,
                "confidence": confidence,
                "source": "text_toc",
            }
        )
        if len(items) >= MAX_OUTLINE_ITEMS:
            break

    if len(items) < 3:
        return []
    return _with_page_ends(items)


def _infer_headings(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    items: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    current_page: int | None = None

    for raw_line in _candidate_lines(text, max_lines=3000):
        page_match = re.search(r"\[(?:PDF|PDF OCR|PPT slide)\s+(?:page|slide)?\s*(\d+)\]", raw_line, re.I)
        if page_match:
            current_page = _positive_int(page_match.group(1))
            continue

        line = _normalize_spaces(raw_line.strip())
        if not line:
            continue
        match = _match_heading_line(line)
        if match is None:
            continue
        title, level = match
        title = _clean_title(title)
        if not _valid_title(title) or title in seen_titles:
            continue
        seen_titles.add(title)
        items.append(
            {
                "title": title,
                "level": level,
                "page_start": current_page,
                "page_end": None,
                "order": len(items) + 1,
                "confidence": 0.68,
                "source": "heading_infer",
            }
        )
        if len(items) >= MAX_OUTLINE_ITEMS:
            break

    if len(items) < 3:
        return []
    return _with_page_ends(items)


async def _refine_outline_with_llm(
    items: list[dict[str, Any]], filename: str
) -> list[dict[str, Any]]:
    fallback = {"items": items[:MAX_OUTLINE_ITEMS]}
    result = await DeepSeekClient().complete_json(
        system_prompt=(
            "你是课程资料目录清洗器。请只基于给定目录条目做轻量整理，"
            "合并重复标题，过滤页眉页脚和非章节噪声，修正明显层级错误。"
            "不要新增资料中没有的章节，必须返回 JSON。"
        ),
        user_payload={
            "filename": filename,
            "items": items[:MAX_OUTLINE_ITEMS],
            "schema": {
                "items": [
                    {
                        "title": "章节标题",
                        "level": 1,
                        "page_start": 1,
                        "page_end": 12,
                        "order": 1,
                        "confidence": 0.9,
                        "source": "llm_refined",
                    }
                ]
            },
        },
        fallback=fallback,
    )
    raw_items = result.get("items")
    if not isinstance(raw_items, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        title = _clean_title(str(raw.get("title") or ""))
        if not _valid_title(title) or title in seen_titles:
            continue
        seen_titles.add(title)
        normalized.append(
            {
                "title": title,
                "level": _clamp_level(raw.get("level")),
                "page_start": _positive_int(raw.get("page_start")),
                "page_end": _positive_int(raw.get("page_end")),
                "order": len(normalized) + 1,
                "confidence": _confidence(raw.get("confidence"), default=0.8),
                "source": "llm_refined",
            }
        )
        if len(normalized) >= MAX_OUTLINE_ITEMS:
            break
    return _with_page_ends(normalized)


def outline_context_for_goal(materials: list[models.CourseMaterial]) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    for material in materials:
        items = getattr(material, "outline_json", None) or []
        if not isinstance(items, list) or not items:
            continue
        context.append(
            {
                "material_id": material.id,
                "filename": material.filename,
                "status": getattr(material, "outline_status", None) or "unavailable",
                "source": getattr(material, "outline_source", None) or "unknown",
                "items": items[:MAX_OUTLINE_ITEMS],
            }
        )
    return context


def outline_topics_from_context(context: list[dict[str, Any]]) -> list[str]:
    topics: list[str] = []
    for material in context:
        for item in material.get("items") or []:
            title = str(item.get("title") or "").strip()
            if title and title not in topics:
                topics.append(title)
            if len(topics) >= 30:
                return topics
    return topics


def _match_toc_line(line: str) -> tuple[str, int, int | None] | None:
    stripped = _strip_leading_markdown(line)
    page = None
    page_match = re.search(r"(?:\.{2,}|…{1,}|\s{2,})\s*(\d{1,4})$", stripped)
    if page_match:
        page = _positive_int(page_match.group(1))
        stripped = stripped[: page_match.start()].strip()

    patterns = [
        (r"^(第\s*[一二三四五六七八九十百千万\d]+\s*[章节篇讲])\s*[:：、.\-]?\s*(.+)$", 1),
        (r"^((?:\d+\.){1,3}\d*)\s+(.+)$", None),
        (r"^(Chapter\s+\d+)\s*[:：.\-]?\s*(.+)$", 1),
        (r"^(Section\s+\d+(?:\.\d+)*)\s*[:：.\-]?\s*(.+)$", 2),
    ]
    for pattern, fixed_level in patterns:
        match = re.match(pattern, stripped, flags=re.I)
        if not match:
            continue
        prefix = _normalize_spaces(match.group(1))
        title = _normalize_spaces(match.group(2))
        level = fixed_level if fixed_level is not None else min(prefix.count(".") + 1, 4)
        return f"{prefix} {title}".strip(), level, page
    return None


def _match_heading_line(line: str) -> tuple[str, int] | None:
    stripped = _strip_leading_markdown(line)
    markdown_match = re.match(r"^(#{1,4})\s+(.+)$", line)
    if markdown_match:
        return markdown_match.group(2), min(len(markdown_match.group(1)), 4)
    toc_match = _match_toc_line(stripped)
    if toc_match:
        title, level, _ = toc_match
        return title, level
    if 4 <= len(stripped) <= 36 and _looks_like_title_text(stripped):
        return stripped, 2
    return None


def _candidate_lines(text: str, *, max_lines: int) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def _front_document_text(text: str, *, max_pages: int = 20) -> str:
    if not text:
        return ""
    parts: list[str] = []
    current: list[str] = []
    page_count = 0
    for line in text.splitlines():
        if re.match(r"\[(?:PDF|PDF OCR)\s+page\s+\d+\]", line.strip(), re.I):
            if current:
                parts.append("\n".join(current))
                current = []
            page_count += 1
            if page_count > max_pages:
                break
        current.append(line)
    if current and page_count <= max_pages:
        parts.append("\n".join(current))
    return "\n".join(parts) if page_count else "\n".join(text.splitlines()[:900])


def _ocr_pages_text(ocr_pages: list[Any] | None, *, max_pages: int = 20) -> str:
    if not ocr_pages:
        return ""
    parts = []
    for page in ocr_pages[:max_pages]:
        page_index = getattr(page, "page_index", None)
        markdown = getattr(page, "markdown", "")
        if markdown:
            parts.append(f"[PDF OCR page {page_index}]\n{markdown}")
    return "\n\n".join(parts)


def _with_page_ends(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(items, key=lambda item: int(item.get("order") or 0))
    for index, item in enumerate(ordered):
        if item.get("page_end") is not None:
            continue
        current_start = _positive_int(item.get("page_start"))
        next_start = None
        for later in ordered[index + 1 :]:
            next_start = _positive_int(later.get("page_start"))
            if next_start:
                break
        if current_start and next_start and next_start > current_start:
            item["page_end"] = next_start - 1
        else:
            item["page_end"] = None
    for index, item in enumerate(ordered, start=1):
        item["order"] = index
    return ordered


def _clean_title(title: str) -> str:
    title = _strip_leading_markdown(title)
    title = re.sub(r"\s*\.{2,}\s*\d{1,4}$", "", title)
    title = re.sub(r"\s+第?\s*\d{1,4}\s*页$", "", title)
    title = re.sub(r"\s+", " ", title).strip(" -–—:：、.\t")
    return title[:120]


def _valid_title(title: str) -> bool:
    if not 2 <= len(title) <= 120:
        return False
    lowered = title.lower()
    noise_tokens = [
        "copyright",
        "isbn",
        "http://",
        "https://",
        "www.",
        "目录",
        "contents",
        "table of contents",
    ]
    if lowered in noise_tokens or any(token in lowered for token in noise_tokens[:6]):
        return False
    if sum(ch.isdigit() for ch in title) > max(6, len(title) * 0.55):
        return False
    if any(token in title for token in ["\\frac", "\\int", "\\sum", "$$", "\\begin"]):
        return False
    return True


def _looks_like_toc_header(line: str) -> bool:
    return line.strip().lower() in {"目录", "目 录", "contents", "table of contents"}


def _looks_like_title_text(line: str) -> bool:
    if line.endswith(("。", "，", ",", ";", "；")):
        return False
    if len(line.split()) > 8:
        return False
    return bool(
        re.search(r"(章|节|篇|讲|Chapter|Section|绪论|引言|复习|习题|定理|积分|导数|级数|矩阵|概率|极限)", line, re.I)
    )


def _strip_leading_markdown(line: str) -> str:
    return re.sub(r"^(#{1,6}\s+|[-*+]\s+|\d+[.)、]\s+)", "", line).strip()


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def _clamp_level(value: Any) -> int:
    try:
        level = int(value)
    except Exception:
        level = 1
    return max(1, min(level, 4))


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except Exception:
        return None
    return number if number > 0 else None


def _confidence(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except Exception:
        return default
    return max(0.0, min(1.0, number))
