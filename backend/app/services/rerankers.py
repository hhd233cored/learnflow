from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Protocol


class Reranker(Protocol):
    """RAG reranker 协议。"""

    def name(self) -> str:
        """返回 reranker 名称。"""

    def rerank(
        self, query: str, hits: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]:
        """重排候选片段，并返回前 top_k 条。"""


class BgeReranker:
    """基于 BAAI/bge-reranker-v2-m3 的二阶段重排器。

    reranker 是交叉编码器，比 embedding 更慢，但排序更准。默认关闭，
    只有 `RERANKER_PROVIDER=bge` 或 `bge-reranker` 时才会启用。
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        device: str = "auto",
        batch_size: int = 8,
        use_fp16: bool = False,
    ) -> None:
        self.model_name = model_name
        self.device = device.strip() if device else "auto"
        self.batch_size = batch_size
        self.use_fp16 = use_fp16
        self._model: Any | None = None

    def name(self) -> str:
        """返回 Chroma 之外可读的 reranker 名称。"""

        safe_model = re.sub(r"[^a-zA-Z0-9_.-]+", "-", self.model_name).strip("-")
        return f"learnflow-bge-reranker-{safe_model}"

    def rerank(
        self, query: str, hits: list[dict[str, Any]], top_k: int
    ) -> list[dict[str, Any]]:
        """用 query-document pair 分数重排候选片段。"""

        if not hits:
            return []
        pairs = [[query, str(hit.get("content") or "")] for hit in hits]
        scores = self._compute_scores(pairs)
        ranked_hits = []
        for hit, score in zip(hits, scores, strict=False):
            enriched = dict(hit)
            enriched["rerank_score"] = float(score)
            ranked_hits.append(enriched)
        ranked_hits.sort(key=lambda item: item.get("rerank_score", 0.0), reverse=True)
        return ranked_hits[:top_k]

    def _compute_scores(self, pairs: list[list[str]]) -> list[float]:
        """兼容不同 FlagEmbedding 版本的 compute_score 签名。"""

        model = self._load_model()
        try:
            scores = model.compute_score(
                pairs,
                batch_size=self.batch_size,
                normalize=True,
            )
        except TypeError:
            try:
                scores = model.compute_score(pairs, batch_size=self.batch_size)
            except TypeError:
                scores = model.compute_score(pairs)
        if not isinstance(scores, list):
            if hasattr(scores, "tolist"):
                scores = scores.tolist()
            else:
                scores = [scores]
        return [float(score) for score in scores]

    def _load_model(self) -> Any:
        """懒加载 reranker，避免后端启动时下载或加载模型。"""

        if self._model is not None:
            return self._model
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:
            raise RuntimeError(
                "RERANKER_PROVIDER=bge requires FlagEmbedding. "
                "Run `pip install -r backend/requirements-bge.txt`, then restart backend."
            ) from exc

        kwargs: dict[str, Any] = {"use_fp16": self.use_fp16}
        if self.device and self.device.lower() != "auto":
            kwargs["device"] = self.device
        try:
            self._model = FlagReranker(self.model_name, **kwargs)
        except TypeError:
            kwargs.pop("device", None)
            self._model = FlagReranker(self.model_name, **kwargs)

        # ── transformers >=5.x 移除了 prepare_for_model ──
        # FlagEmbedding 1.4.0 的 compute_score_single_gpu 还依赖它（Token ID 级拼接），
        # 而 XLMRobertaTokenizer 没有这个方法。我们在加载后的 tokenizer 实例上动态补上。
        if not hasattr(self._model.tokenizer, "prepare_for_model"):

            def _prepare_for_model(
                self,
                query_ids: list[int],
                passage_ids: list[int],
                truncation: str = "only_second",
                max_length: int | None = None,
                padding: bool = False,
            ) -> dict[str, list[int]]:
                """模拟 PreTrainedTokenizerFast.prepare_for_model。

                用于 transformers>=5.x 下 XLMRobertaTokenizer 缺失该方法的降级。
                """
                # XLM-RoBERTa: [CLS]=0, [SEP]=2 — 3 个 special tokens
                special_tokens_count = 3  # CLS + SEP + SEP
                if max_length is not None and truncation == "only_second":
                    max_passage = max_length - len(query_ids) - special_tokens_count
                    if max_passage < 0:
                        max_passage = 0
                    passage_ids = passage_ids[:max_passage]

                input_ids = (
                    [self.cls_token_id]
                    + list(query_ids)
                    + [self.sep_token_id]
                    + list(passage_ids)
                    + [self.sep_token_id]
                )
                return {"input_ids": input_ids, "attention_mask": [1] * len(input_ids)}

            import types

            self._model.tokenizer.prepare_for_model = types.MethodType(
                _prepare_for_model, self._model.tokenizer
            )

        return self._model


@lru_cache
def get_reranker(
    provider: str = "none",
    model_name: str = "BAAI/bge-reranker-v2-m3",
    device: str = "auto",
    batch_size: int = 8,
    use_fp16: bool = False,
) -> Reranker | None:
    """根据配置返回 reranker；默认关闭。"""

    normalized_provider = (provider or "none").strip().lower().replace("_", "-")
    if normalized_provider in {"", "none", "off", "false", "disabled"}:
        return None
    if normalized_provider in {"bge", "bge-reranker", "bge-reranker-v2-m3"}:
        return BgeReranker(
            model_name=model_name or "BAAI/bge-reranker-v2-m3",
            device=device or "auto",
            batch_size=batch_size,
            use_fp16=use_fp16,
        )
    raise ValueError(
        f"Unsupported RERANKER_PROVIDER={provider!r}. Use 'none' or 'bge'."
    )
