from __future__ import annotations

from sqlalchemy import select

from app import models
from app.db.session import SessionLocal
from app.schemas import GoalCreate
from app.services.knowledge_base import ChromaKnowledgeBase
from app.services.material_outline import outline_context_for_goal


def knowledge_context_for_goal(goal_id: int, payload: GoalCreate) -> dict:
    """为 Planner Agent 检索目标级课程资料上下文。

    总计划还没有具体 day/topic，因此用学习目标标题和重点章节作为查询词。
    如果用户没有上传资料或 Chroma 暂时不可用，返回空列表，不影响普通计划生成。
    """

    query = " ".join([payload.title, *payload.key_topics]).strip()
    outlines = _outline_context(goal_id)
    chunks: list[dict] = []
    if not query:
        return {"material_outlines": outlines, "retrieved_chunks": chunks}
    try:
        chunks = ChromaKnowledgeBase().query(goal_id, query, top_k=6)
    except Exception:
        chunks = []
    return {"material_outlines": outlines, "retrieved_chunks": chunks}


def _outline_context(goal_id: int) -> list[dict]:
    db = SessionLocal()
    try:
        materials = list(
            db.scalars(
                select(models.CourseMaterial)
                .where(models.CourseMaterial.goal_id == goal_id)
                .order_by(models.CourseMaterial.created_at.asc())
            ).all()
        )
        return outline_context_for_goal(materials)
    except Exception:
        return []
    finally:
        db.close()
