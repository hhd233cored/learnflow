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
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.on_event("startup")
    def startup() -> None:
        # MVP convenience: create tables automatically. In a production version
        # this should move to Alembic migrations.
        Base.metadata.create_all(bind=engine)

    return app


app = create_app()

