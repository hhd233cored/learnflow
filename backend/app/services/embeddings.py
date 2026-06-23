from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from functools import lru_cache
from typing import Any, Protocol


logger = logging.getLogger(__name__)


class EmbeddingFunction(Protocol):
    """Chroma 兼容的 embedding function 协议。"""

    def name(self) -> str:
        """返回 embedding function 名称。"""

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        """把文本列表转换为向量列表。"""


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


class BgeM3EmbeddingFunction:
    """基于 BAAI/bge-m3 的 Chroma embedding function。

    BGE-M3 模型较大，首次使用时会加载模型并可能从 Hugging Face/ModelScope
    下载权重。默认不启用它，只有 `EMBEDDING_PROVIDER=bge-m3` 时才会使用。
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: str = "auto",
        batch_size: int = 12,
        use_fp16: bool = False,
        max_length: int = 8192,
        api_token: str = "",
    ) -> None:
        self.model_name = model_name
        self.device = device.strip() if device else "auto"
        self.batch_size = batch_size
        self.use_fp16 = use_fp16
        self.max_length = max_length
        self.api_token = api_token
        self._model: Any | None = None

    def name(self) -> str:
        """新版 Chroma embedding function 校验所需的名称。"""

        safe_model = re.sub(r"[^a-zA-Z0-9_.-]+", "-", self.model_name).strip("-")
        return f"learnflow-bge-m3-{safe_model}"

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        """对一批文本做 BGE-M3 dense embedding。"""

        texts = [str(item or "") for item in input]
        if not texts:
            return []

        encoded = self._load_model().encode(
            texts,
            batch_size=self.batch_size,
            max_length=self.max_length,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        dense_vectors = encoded["dense_vecs"]
        return [_to_float_list(vector) for vector in dense_vectors]

    def embed_query(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        """对查询文本做 embedding，用于兼容 Chroma 1.x。"""

        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        """对文档文本做 embedding，用于兼容 Chroma 1.x。"""

        return self(input)

    def _load_model(self) -> Any:
        """懒加载 BGE-M3 模型，避免后端启动时立刻加载大模型。"""

        if self._model is not None:
            return self._model

        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=bge-m3 requires FlagEmbedding. "
                "Run `pip install -r backend/requirements-bge.txt`, then restart backend."
            ) from exc

        # 注入 HF Token 以便 huggingface_hub 用认证身份下载，带宽更高
        token = self.api_token or os.environ.get("HF_TOKEN") or ""
        if token:
            os.environ.setdefault("HF_TOKEN", token)

        kwargs: dict[str, Any] = {"use_fp16": self.use_fp16}
        if self.device and self.device.lower() != "auto":
            kwargs["device"] = self.device

        try:
            self._model = BGEM3FlagModel(self.model_name, **kwargs)
        except TypeError:
            kwargs.pop("device", None)
            self._model = BGEM3FlagModel(self.model_name, **kwargs)
        return self._model


class HuggingFaceApiEmbeddingFunction:
    """通过 HuggingFace Inference API 远程调用 bge-m3 生成 embedding。

    优先使用 ``huggingface_hub`` SDK；若未安装则自动 fallback 到 HTTP 直连。
    不需要 GPU，也不需要下载模型权重，适合本地算力不足但需要高质量
    embedding 的场景。

    在 ``EMBEDDING_PROVIDER=hf-api`` 时启用，需配置环境变量 ``HF_TOKEN``。
    """

    def __init__(
        self,
        model: str = "BAAI/bge-m3",
        api_key: str = "",
        batch_size: int = 32,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("HF_TOKEN", "")
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._client: Any | None = None
        self._use_sdk: bool | None = None  # None = 尚未检测

    def name(self) -> str:
        """新版 Chroma embedding function 校验所需的名称。"""

        safe_model = re.sub(r"[^a-zA-Z0-9_.-]+", "-", self.model).strip("-")
        return f"learnflow-hf-api-{safe_model}"

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        """对一批文本做 embedding，通过 HF Inference API 远程调用。"""

        texts = [str(item or "") for item in input]
        if not texts:
            return []

        if self._use_sdk is None:
            self._use_sdk = self._detect_sdk()

        total = len(texts)
        logger.info(
            "HF API embedding 开始：%d 条文本，batch_size=%d",
            total,
            self.batch_size,
        )

        all_embeddings: list[list[float]] = []
        for i in range(0, total, self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_idx = i // self.batch_size + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size
            logger.info(
                "HF API embedding 进度：batch %d/%d（%d 条）",
                batch_idx,
                total_batches,
                len(batch),
            )
            batch_result = (
                self._encode_via_sdk(batch)
                if self._use_sdk
                else self._encode_via_http(batch)
            )
            all_embeddings.extend(batch_result)

        logger.info("HF API embedding 完成：共 %d 条", total)
        return all_embeddings

    def embed_query(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        """对查询文本做 embedding，用于兼容 Chroma 1.x。"""

        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        """对文档文本做 embedding，用于兼容 Chroma 1.x。"""

        return self(input)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_sdk() -> bool:
        """检测 ``huggingface_hub`` 是否可用。"""

        try:
            import huggingface_hub  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_client(self) -> Any:
        """懒创建 HF InferenceClient 实例。"""

        if self._client is None:
            from huggingface_hub import InferenceClient

            self._client = InferenceClient(api_key=self.api_key)
        return self._client

    def _encode_via_sdk(self, texts: list[str]) -> list[list[float]]:
        """通过 ``huggingface_hub.InferenceClient.feature_extraction`` 编码。"""

        client = self._get_client()
        results: list[list[float]] = []
        for text in texts:
            for attempt in range(1, self.max_retries + 1):
                try:
                    emb = client.feature_extraction(text, model=self.model)
                    results.append(self._pool_embedding(emb))
                    break
                except Exception as exc:
                    if attempt == self.max_retries:
                        raise RuntimeError(
                            f"HF SDK feature_extraction failed after "
                            f"{self.max_retries} attempts: {exc}"
                        ) from exc
        return results

    def _encode_via_http(self, texts: list[str]) -> list[list[float]]:
        """通过原始 HTTP POST 调用 HF Inference API 的 feature-extraction pipeline。"""

        import httpx

        api_url = (
            f"https://router.huggingface.co/hf-inference/models"
            f"/{self.model}/pipeline/feature-extraction"
        )
        headers = {"Authorization": f"Bearer {self.api_key}"}
        results: list[list[float]] = []
        with httpx.Client(timeout=httpx.Timeout(60.0)) as client:
            for text in texts:
                for attempt in range(1, self.max_retries + 1):
                    try:
                        payload: dict[str, Any] = {
                            "inputs": text,
                            "options": {"wait_for_model": True},
                        }
                        resp = client.post(api_url, headers=headers, json=payload)
                        resp.raise_for_status()
                        data = resp.json()
                        results.append(self._pool_embedding(data))
                        break
                    except Exception as exc:
                        if attempt == self.max_retries:
                            raise RuntimeError(
                                f"HF HTTP feature_extraction failed after "
                                f"{self.max_retries} attempts: {exc}"
                            ) from exc
        return results

    @staticmethod
    def _pool_embedding(data: Any) -> list[float]:
        """将 HF API 返回的 embedding 统一为 1D float list。

        处理两种返回格式：
        - 已经是 1D list/array（句子级向量）→ 直接返回
        - 2D list/array（per-token）        → mean pooling 得到句子级向量
        """

        # huggingface_hub SDK 可能返回 numpy ndarray，统一转 list
        if hasattr(data, "tolist"):
            data = data.tolist()

        if not isinstance(data, list):
            raise TypeError(f"Expected list/array, got {type(data).__name__}")
        if not data:
            raise ValueError("Empty embedding response from HF API")

        # 情况 1：已经是 1D embedding 向量
        if not isinstance(data[0], list):
            return [float(x) for x in data]

        # 情况 2：per-token embeddings → mean pooling
        token_embs = [[float(x) for x in row] for row in data]
        if not token_embs:
            raise ValueError("Empty token-level embedding from HF API")

        dim = len(token_embs[0])
        pooled = [0.0] * dim
        for token_vec in token_embs:
            for j, val in enumerate(token_vec):
                pooled[j] += val
        n = len(token_embs)
        return [v / n for v in pooled]


def _to_float_list(vector: Any) -> list[float]:
    """把 numpy/torch/list 向量统一转成 Chroma 可序列化的 float list。"""

    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(item) for item in vector]


@lru_cache
def get_embedding_function(
    provider: str = "hash",
    model_name: str = "BAAI/bge-m3",
    device: str = "auto",
    batch_size: int = 12,
    use_fp16: bool = False,
    api_token: str = "",
) -> EmbeddingFunction:
    """根据配置返回 Chroma embedding function，并缓存模型实例。"""

    normalized_provider = (provider or "hash").strip().lower().replace("_", "-")
    if normalized_provider in {"hash", "local", "demo"}:
        return HashEmbeddingFunction()
    if normalized_provider in {"bge", "bge-m3", "bge_m3"}:
        return BgeM3EmbeddingFunction(
            model_name=model_name or "BAAI/bge-m3",
            device=device or "auto",
            batch_size=batch_size,
            use_fp16=use_fp16,
            api_token=api_token,
        )
    if normalized_provider in {"hf-api", "huggingface", "hf"}:
        return HuggingFaceApiEmbeddingFunction(
            model=model_name or "BAAI/bge-m3",
            api_key=api_token,
            batch_size=batch_size,
        )
    raise ValueError(
        f"Unsupported EMBEDDING_PROVIDER={provider!r}. "
        f"Use 'hash', 'bge-m3', or 'hf-api'."
    )
