from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.routes import router
from app.core.config import get_settings
from app.db.base import Base
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

    inspector = inspect(engine)
    if not inspector.has_table("learning_goals"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("learning_goals")}
    statements: list[str] = []
    if "goal_type" not in existing_columns:
        statements.append(
            "ALTER TABLE learning_goals ADD COLUMN goal_type VARCHAR(20) DEFAULT 'exam' NOT NULL"
        )
    if "duration_days" not in existing_columns:
        statements.append("ALTER TABLE learning_goals ADD COLUMN duration_days INTEGER")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


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

        # MVP 阶段为了方便自动建表；生产版本应迁移到 Alembic。
        Base.metadata.create_all(bind=engine)
        ensure_demo_schema_columns()

    return app


app = create_app()
