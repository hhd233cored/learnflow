from __future__ import annotations

from sqlalchemy.orm import Session

from app import crud, models
from app.agents import workflow
from app.schemas import GoalCreate
from app.services.planning_context import knowledge_context_for_goal


async def generate_and_store_goal_plan(
    db: Session, goal: models.LearningGoal
) -> models.LearningGoal:
    """异步生成并保存某个学习目标的完整计划。

    Celery 任务会调用这个函数完成长计划生成。这里把数据库中的目标对象
    转回 `GoalCreate`，复用现有 Planner Agent 工作流和输出校验逻辑。
    """

    payload = GoalCreate(
        title=goal.title,
        goal_type=getattr(goal, "goal_type", "exam"),
        exam_date=goal.exam_date,
        duration_days=goal.duration_days,
        daily_minutes=goal.daily_minutes,
        current_level=goal.current_level,
        key_topics=goal.key_topics,
    )
    knowledge_context = knowledge_context_for_goal(goal.id, payload)
    daily_plans = await workflow.generate_plan(payload, knowledge_context)
    return crud.replace_goal_plans(db, goal, daily_plans)
