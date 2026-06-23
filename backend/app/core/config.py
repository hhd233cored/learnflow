from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量读取的运行时配置。

    默认数据库指向本地 SQLite，方便开发者不装 Docker 也能启动后端。
    Docker Compose 会用 PostgreSQL 连接地址覆盖这个默认值。
    """

    app_name: str = "LearnFlow API"
    database_url: str = "sqlite:///./studyagent.db"
    redis_url: str = "redis://localhost:6379/0"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    ocr_provider: str = "none"
    paddle_ocr_token: str = ""
    paddle_ocr_job_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    paddle_ocr_model: str = "PaddleOCR-VL-1.6"
    ocr_storage_dir: str = "./storage/ocr"
    ocr_poll_interval_seconds: float = 5.0
    ocr_poll_timeout_seconds: int = 600
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    material_upload_dir: str = "./storage/materials"
    chroma_persist_dir: str = "./storage/chroma"
    embedding_provider: str = "hash"
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "auto"
    embedding_batch_size: int = 12
    embedding_use_fp16: bool = False
    reranker_provider: str = "none"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_device: str = "auto"
    reranker_batch_size: int = 8
    reranker_use_fp16: bool = False
    reranker_candidate_count: int = 30
    rag_hybrid_search_enabled: bool = False
    rag_lexical_candidate_count: int = 30
    chunk_size: int = 800
    chunk_overlap: int = 120
    rag_enrich_max_chunks: int = 12
    hf_api_token: str = Field(
        default="",
        alias="HF_TOKEN",
        description="HuggingFace API token，EMBEDDING_PROVIDER=hf-api 时需要",
    )

    # 本地启动脚本会先切到 backend/，因此这里使用相对路径读取 backend/.env。
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """从逗号分隔的 `.env` 字符串中解析 CORS origin 列表。

        把 `cors_origins` 保持为字符串，可以避免 Pydantic 把 `.env`
        里的值当作 JSON 解析。开发时可以继续使用这种常见写法：
        `CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000`.
        """

        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """返回缓存后的应用配置。

    配置会被缓存，避免每次 API 调用都重新读取 `.env`。修改环境变量后，
    需要重启 Uvicorn 才能生效。
    """

    return Settings()
