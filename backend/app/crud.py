from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.schemas import GoalCreate


def create_goal_with_plan(
    db: Session, payload: GoalCreate, daily_plans: list[dict]
) -> models.LearningGoal:
    goal = models.LearningGoal(
        title=payload.title,
        exam_date=payload.exam_date,
        daily_minutes=payload.daily_minutes,
        current_level=payload.current_level,
        key_topics=payload.key_topics,
    )
    db.add(goal)
    db.flush()

    for item in daily_plans:
        db.add(
            models.StudyPlan(
                goal_id=goal.id,
                day_index=item["day_index"],
                plan_date=item["plan_date"],
                topic=item["topic"],
                objective=item["objective"],
            )
        )

    db.commit()
    return get_goal(db, goal.id)


def get_goal(db: Session, goal_id: int) -> models.LearningGoal | None:
    stmt = (
        select(models.LearningGoal)
        .where(models.LearningGoal.id == goal_id)
        .options(selectinload(models.LearningGoal.plans))
    )
    return db.scalars(stmt).first()


def get_plan(db: Session, plan_id: int) -> models.StudyPlan | None:
    stmt = (
        select(models.StudyPlan)
        .where(models.StudyPlan.id == plan_id)
        .options(
            selectinload(models.StudyPlan.goal),
            selectinload(models.StudyPlan.tasks),
            selectinload(models.StudyPlan.reviews),
        )
    )
    return db.scalars(stmt).first()


def list_tasks(db: Session, plan_id: int) -> list[models.StudyTask]:
    stmt = select(models.StudyTask).where(models.StudyTask.plan_id == plan_id)
    return list(db.scalars(stmt).all())


def replace_tasks(db: Session, plan_id: int, tasks: list[dict]) -> list[models.StudyTask]:
    # Regenerating tasks should keep the demo deterministic instead of
    # accumulating duplicate cards for the same day.
    db.query(models.StudyTask).filter(models.StudyTask.plan_id == plan_id).delete()
    for item in tasks:
        db.add(
            models.StudyTask(
                plan_id=plan_id,
                title=item["title"],
                description=item["description"],
                estimated_minutes=item["estimated_minutes"],
                task_type=item["task_type"],
            )
        )
    db.commit()
    return list_tasks(db, plan_id)


def update_task_status(
    db: Session, task_id: int, status: str
) -> models.StudyTask | None:
    task = db.get(models.StudyTask, task_id)
    if task is None:
        return None
    task.status = status
    db.commit()
    db.refresh(task)
    return task


def create_review(
    db: Session,
    plan: models.StudyPlan,
    review: dict,
    feedback: str,
) -> models.StudyReview:
    item = models.StudyReview(
        goal_id=plan.goal_id,
        plan_id=plan.id,
        completion_rate=review["completion_rate"],
        weak_points=review["weak_points"],
        suggestions=review["suggestions"],
        summary=review["summary"],
        feedback=feedback,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def latest_review_for_plan(
    db: Session, plan_id: int
) -> models.StudyReview | None:
    stmt = (
        select(models.StudyReview)
        .where(models.StudyReview.plan_id == plan_id)
        .order_by(models.StudyReview.created_at.desc())
    )
    return db.scalars(stmt).first()


def get_plan_by_day(
    db: Session, goal_id: int, day_index: int
) -> models.StudyPlan | None:
    stmt = select(models.StudyPlan).where(
        models.StudyPlan.goal_id == goal_id,
        models.StudyPlan.day_index == day_index,
    )
    return db.scalars(stmt).first()


def apply_adjustment(
    db: Session,
    goal_id: int,
    from_day: int,
    tomorrow_plan: models.StudyPlan,
    adjustment: dict,
) -> models.PlanAdjustment:
    item = models.PlanAdjustment(
        goal_id=goal_id,
        from_day=from_day,
        original_topic=tomorrow_plan.topic,
        adjusted_topic=adjustment["adjusted_topic"],
        original_objective=tomorrow_plan.objective,
        adjusted_objective=adjustment["adjusted_objective"],
        reason=adjustment["reason"],
    )
    tomorrow_plan.topic = adjustment["adjusted_topic"]
    tomorrow_plan.objective = adjustment["adjusted_objective"]
    tomorrow_plan.adjusted = True
    tomorrow_plan.adjustment_reason = adjustment["reason"]
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

