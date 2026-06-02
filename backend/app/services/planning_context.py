from __future__ import annotations

from app.schemas import GoalCreate
from app.services.knowledge_base import ChromaKnowledgeBase


def knowledge_context_for_goal(goal_id: int, payload: GoalCreate) -> list[dict]:
    """为 Planner Agent 检索目标级课程资料上下文。

    总计划还没有具体 day/topic，因此用学习目标标题和重点章节作为查询词。
    如果用户没有上传资料或 Chroma 暂时不可用，返回空列表，不影响普通计划生成。
    """

    query = " ".join([payload.title, *payload.key_topics]).strip()
    if not query:
        return []
    try:
        return ChromaKnowledgeBase().query(goal_id, query, top_k=6)
    except Exception:
        return []
