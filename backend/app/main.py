import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 强制 HuggingFace transformers 只读本地缓存，避免连接 Hub 超时
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from app.api.routes import router
from app.core.config import get_settings
from app.db.base import Base
from app.db.schema import ensure_demo_schema_columns as ensure_demo_schema_columns_for_engine
from app.db.session import engine

# Import models before create_all so SQLAlchemy registers every table.
from app import models  # noqa: F401

settings = get_settings()


def ensure_demo_schema_columns() -> None:
    """为无 Alembic 的本地 Demo 补齐新增列。

    项目第一版直接使用 `create_all`，它只会创建缺失表，不会给已存在的表加列。
    因此这里在启动时做一次轻量检查，让旧的 SQLite/PostgreSQL 本地库也能继续用。
    正式生产环境仍建议改为 Alembic migration。
    """

    ensure_demo_schema_columns_for_engine(engine)


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""

    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.on_event("startup")
    def startup() -> None:
        """MVP 阶段在应用启动时自动创建数据库表。

        这样本地开发更简单。正式生产环境应替换为 Alembic 迁移。
        """

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        # MVP 阶段为了方便自动建表；生产版本应迁移到 Alembic。
        Base.metadata.create_all(bind=engine)
        ensure_demo_schema_columns()

    return app


app = create_app()
