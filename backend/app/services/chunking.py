from __future__ import annotations

import re


def split_text_into_chunks(
    text: str, chunk_size: int = 800, chunk_overlap: int = 120
) -> list[str]:
    """把课程文本切分成适合检索的稳定 chunk。

    切分时优先保留段落边界；遇到过长段落时，再退回到带重叠的字符窗口，
    确保长 PDF 页面也能被索引。
    """

    normalized = _normalize_text(text)
    if not normalized:
        return []

    paragraphs = [item.strip() for item in re.split(r"\n{2,}", normalized) if item.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_window_split(paragraph, chunk_size, chunk_overlap))
            continue

        next_text = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(next_text) <= chunk_size:
            current = next_text
        else:
            chunks.append(current)
            current = paragraph

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if len(chunk.strip()) >= 20]


def _normalize_text(text: str) -> str:
    """切分前先规范化空白字符。"""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _window_split(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """使用带重叠的窗口切分单个长段落。"""

    chunks = []
    start = 0
    step = max(1, chunk_size - chunk_overlap)
    while start < len(text):
        chunk = text[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks
