from __future__ import annotations

import asyncio
import logging
from typing import Any

from app import crud, models
from app.agents import workflow
from app.db.session import SessionLocal
from app.schemas import GoalCreate
from app.services.material_pipeline import build_material_knowledge_base

logger = logging.getLogger(__name__)
from app.services.planning_context import knowledge_context_for_goal


def start_goal_with_materials_job(job_id: int, goal_id: int, material_ids: list[int]) -> None:
    """在当前 FastAPI 进程内启动生成计划任务。

    本地 Demo 模式不依赖 Redis/Celery。任务进度仍然写入 jobs 表，前端继续通过
    `/jobs/{job_id}` 轮询即可。限制是后端进程重启会中断正在运行的任务。
    """

    asyncio.create_task(run_goal_with_materials_job(job_id, goal_id, material_ids))


async def run_goal_with_materials_job(
    job_id: int,
    goal_id: int,
    material_ids: list[int],
) -> None:
    """处理“上传资料 -> OCR/RAG -> Planner Agent -> 保存计划”的完整后台流程。"""

    db = SessionLocal()
    failed_materials: list[dict[str, str]] = []
    try:
        job = _get_job(db, job_id)
        goal = _get_goal(db, goal_id)
        payload = _goal_payload(goal)

        crud.mark_job_running(
            db,
            job,
            progress=5,
        )
        _update_job(
            db,
            job,
            8,
            {
                "stage": "materials_saved",
                "message": "学习目标和资料已保存，准备处理课程资料。",
                "goal_id": goal.id,
                "material_count": len(material_ids),
            },
        )

        materials = [
            material
            for material_id in material_ids
            if (material := crud.get_material(db, material_id)) is not None
        ]
        material_total = max(1, len(materials))
        for index, material in enumerate(materials):
            start = 10 + int(index * 60 / material_total)
            end = 10 + int((index + 1) * 60 / material_total)
            try:
                _update_job(
                    db,
                    job,
                    start,
                    {
                        "stage": "material_processing",
                        "message": f"正在处理资料：{material.filename}",
                        "goal_id": goal.id,
                        "material_id": material.id,
                        "current_file": material.filename,
                        "file_index": index + 1,
                        "file_count": len(materials),
                    },
                )

                await build_material_knowledge_base(
                    db,
                    material,
                    progress_callback=lambda stage, payload, material=material, start=start, end=end: _material_progress(
                        db,
                        job,
                        material,
                        stage,
                        payload,
                        start,
                        end,
                        index + 1,
                        len(materials),
                    ),
                )
                _update_job(
                    db,
                    job,
                    end,
                    {
                        "stage": "rag_ready",
                        "message": f"知识库构建完成：{material.filename}",
                        "goal_id": goal.id,
                        "material_id": material.id,
                        "current_file": material.filename,
                        "file_index": index + 1,
                        "file_count": len(materials),
                    },
                )
            except Exception as exc:
                logger.exception(
                    "[%s] 资料建库异常", material.filename
                )
                crud.mark_material_failed(db, material, str(exc))
                failed_materials.append(
                    {"filename": material.filename, "error": str(exc)[:500]}
                )
                _update_job(
                    db,
                    job,
                    end,
                    {
                        "stage": "material_failed",
                        "message": f"资料处理失败，已跳过：{material.filename}",
                        "goal_id": goal.id,
                        "material_id": material.id,
                        "current_file": material.filename,
                        "file_index": index + 1,
                        "file_count": len(materials),
                        "failed_materials": failed_materials,
                    },
                )

        _update_job(
            db,
            job,
            75,
            {
                "stage": "rag_querying",
                "message": "正在检索课程知识库，准备生成学习计划。",
                "goal_id": goal.id,
                "failed_materials": failed_materials,
            },
        )
        knowledge_context = knowledge_context_for_goal(goal.id, payload)

        _update_job(
            db,
            job,
            82,
            {
                "stage": "planning",
                "message": "正在调用 Planner Agent 生成阶段计划和每日计划。",
                "goal_id": goal.id,
                "knowledge_hits": len(knowledge_context),
                "failed_materials": failed_materials,
            },
        )
        daily_plans = await workflow.generate_plan(payload, knowledge_context)

        _update_job(
            db,
            job,
            94,
            {
                "stage": "saving_plan",
                "message": "正在保存学习计划。",
                "goal_id": goal.id,
                "plan_count": len(daily_plans),
                "failed_materials": failed_materials,
            },
        )
        refreshed_goal = _get_goal(db, goal.id)
        saved_goal = crud.replace_goal_plans(db, refreshed_goal, daily_plans)
        job = _get_job(db, job_id)
        crud.mark_job_success(
            db,
            job,
            {
                "stage": "done",
                "message": "学习计划已生成。",
                "goal_id": saved_goal.id,
                "plan_count": len(saved_goal.plans),
                "failed_materials": failed_materials,
            },
        )
    except Exception as exc:
        logger.exception("后台建库任务整体异常 (goal_id=%s)", goal_id)
        job = crud.get_job(db, job_id)
        if job is not None:
            crud.mark_job_failed(db, job, str(exc))
        goal = crud.get_goal(db, goal_id)
        if goal is not None:
            goal.status = "failed"
            db.commit()
    finally:
        db.close()


def _material_progress(
    db,
    job: models.Job,
    material: models.CourseMaterial,
    stage: str,
    payload: dict[str, Any],
    start: int,
    end: int,
    file_index: int,
    file_count: int,
) -> None:
    """把单个资料内部进度映射到整个计划生成任务的 10%-70% 区间。"""

    span = max(1, end - start)
    stage_ratio = {
        "ocr_prepare": 0.05,
        "ocr_cached": 0.35,
        "chunking": 0.55,
        "parsing": 0.4,
        "enriching": 0.7,
        "indexing": 0.88,
        "rag_ready": 1.0,
    }.get(stage, 0.15)

    total_pages = _as_int(payload.get("total_pages"))
    current_page = _as_int(payload.get("current_page"))
    if stage == "ocr_running" and total_pages and current_page is not None:
        page_ratio = max(0.0, min(1.0, current_page / total_pages))
        stage_ratio = 0.08 + page_ratio * 0.45
    elif stage == "ocr_done":
        stage_ratio = 0.52

    progress = start + int(span * stage_ratio)
    _update_job(
        db,
        job,
        progress,
        {
            "stage": stage,
            "message": payload.get("message") or f"正在处理资料：{material.filename}",
            "goal_id": material.goal_id,
            "material_id": material.id,
            "current_file": material.filename,
            "file_index": file_index,
            "file_count": file_count,
            "current_page": payload.get("current_page"),
            "total_pages": payload.get("total_pages"),
            "chunk_count": payload.get("chunk_count"),
        },
    )


def _update_job(db, job: models.Job, progress: int, result_json: dict[str, Any]) -> None:
    """更新 job 进度，并确保 result_json 至少带有 goal_id/stage/message。"""

    crud.update_job_progress(db, job, progress, result_json=result_json)


def _get_job(db, job_id: int) -> models.Job:
    job = crud.get_job(db, job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    return job


def _get_goal(db, goal_id: int) -> models.LearningGoal:
    goal = crud.get_goal(db, goal_id)
    if goal is None:
        raise ValueError(f"Goal {goal_id} not found")
    return goal


def _goal_payload(goal: models.LearningGoal) -> GoalCreate:
    return GoalCreate(
        title=goal.title,
        goal_type=getattr(goal, "goal_type", "exam"),
        exam_date=goal.exam_date,
        duration_days=goal.duration_days,
        daily_minutes=goal.daily_minutes,
        current_level=goal.current_level,
        key_topics=goal.key_topics,
    )


def _as_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
