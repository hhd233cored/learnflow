from __future__ import annotations

import asyncio

from app import crud
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.material_pipeline import build_material_knowledge_base
from app.services.plan_pipeline import generate_and_store_goal_plan
from app.tasks.celery_app import celery_app


def _ensure_tables() -> None:
    """确保 Celery worker 启动时也能创建缺失的数据表。

    FastAPI 进程会在 startup 中 create_all，但 Celery worker 是独立进程。
    MVP 阶段这里也执行一次 create_all，避免 worker 单独启动时找不到新表。
    生产环境应统一迁移到 Alembic。
    """

    Base.metadata.create_all(bind=engine)


@celery_app.task(name="studyagent.parse_material")
def parse_material_task(job_id: int, material_id: int) -> dict:
    """后台解析课程资料，并写入 Chroma 知识库。

    参数只传递数据库 id，worker 内部重新打开数据库 session，避免跨进程传递
    SQLAlchemy 对象。
    """

    _ensure_tables()
    db = SessionLocal()
    try:
        job = crud.get_job(db, job_id)
        material = crud.get_material(db, material_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        if material is None:
            raise ValueError(f"Material {material_id} not found")

        crud.mark_job_running(db, job, progress=10)
        crud.update_job_progress(
            db,
            job,
            progress=35,
            result_json={"material_id": material.id, "stage": "parsing"},
        )

        material = asyncio.run(build_material_knowledge_base(db, material))

        result = {
            "material_id": material.id,
            "goal_id": material.goal_id,
            "chunk_count": material.chunk_count,
            "chroma_collection": material.chroma_collection,
        }
        crud.mark_job_success(db, job, result)
        return result
    except Exception as exc:
        job = crud.get_job(db, job_id)
        material = crud.get_material(db, material_id)
        if material is not None:
            crud.mark_material_failed(db, material, str(exc))
        if job is not None:
            crud.mark_job_failed(db, job, str(exc))
        return {"error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="studyagent.generate_goal_plan")
def generate_goal_plan_task(job_id: int, goal_id: int) -> dict:
    """后台生成学习目标的完整每日计划。

    这个任务用于处理较长计划生成，避免用户在 API 请求中等待 LLM 完成。
    """

    _ensure_tables()
    db = SessionLocal()
    try:
        job = crud.get_job(db, job_id)
        goal = crud.get_goal(db, goal_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        if goal is None:
            raise ValueError(f"Goal {goal_id} not found")

        crud.mark_job_running(db, job, progress=10)
        crud.update_job_progress(
            db,
            job,
            progress=45,
            result_json={"goal_id": goal.id, "stage": "planning"},
        )

        goal = asyncio.run(generate_and_store_goal_plan(db, goal))
        result = {
            "goal_id": goal.id,
            "plan_count": len(goal.plans),
            "status": goal.status,
        }
        crud.mark_job_success(db, job, result)
        return result
    except Exception as exc:
        job = crud.get_job(db, job_id)
        if job is not None:
            crud.mark_job_failed(db, job, str(exc))
        return {"error": str(exc)}
    finally:
        db.close()
