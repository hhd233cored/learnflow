from celery import Celery

from app.core.config import get_settings

settings = get_settings()

# Celery 使用 Redis 同时作为 broker 和 result backend。
# broker 负责排队任务，backend 负责保存 Celery 自身的任务结果。
celery_app = Celery(
    "studyagent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.jobs"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
)

