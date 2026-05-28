from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine

# Import models before create_all so SQLAlchemy registers every table.
from app import models  # noqa: F401

settings = get_settings()


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

    return app


app = create_app()
