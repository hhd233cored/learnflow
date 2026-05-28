from __future__ import annotations

import hashlib
import math
import re


class HashEmbeddingFunction:
    """用于第一版 Chroma 检索的确定性本地 embedding 函数。

    它刻意保持轻量、离线可运行。语义能力不如真正的 embedding 模型，
    但能让知识库管线稳定跑通；后续可以替换成 DeepSeek/OpenAI/BGE。
    """

    def __init__(self, dimensions: int = 384) -> None:
        """创建固定维度的哈希向量器。"""

        self.dimensions = dimensions

    def name(self) -> str:
        """新版 Chroma embedding function 校验所需的名称。"""

        return f"studyagent-hash-{self.dimensions}"

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        """对一批文本做 embedding。

        不同 Chroma 版本可能会直接调用这个方法。
        """

        return [self._embed(document) for document in input]

    def embed_query(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        """对查询文本做 embedding，用于兼容 Chroma 1.x。"""

        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        """对文档文本做 embedding，用于兼容 Chroma 1.x。"""

        return self(input)

    def _embed(self, text: str) -> list[float]:
        """把文本转换成归一化后的哈希向量。"""

        vector = [0.0] * self.dimensions
        tokens = _tokenize(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            index = value % self.dimensions
            sign = 1.0 if (value >> 8) % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(item * item for item in vector))
        if norm == 0:
            return vector
        return [item / norm for item in vector]


def _tokenize(text: str) -> list[str]:
    """把英文词、中文单字和中文 bigram 切出来用于哈希。"""

    lower = text.lower()
    words = re.findall(r"[a-z0-9_]+", lower)
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    chinese_bigrams = [
        "".join(chinese_chars[index : index + 2])
        for index in range(max(0, len(chinese_chars) - 1))
    ]
    return words + chinese_chars + chinese_bigrams
