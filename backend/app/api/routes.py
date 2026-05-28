from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models
from app.agents import workflow
from app.db.session import get_db
from app.schemas import (
    AdjustmentRequest,
    GoalCreate,
    GoalRead,
    PlanAdjustmentRead,
    ReviewCreate,
    StudyReviewRead,
    StudyTaskRead,
    TaskStatusUpdate,
)

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/goals", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
async def create_goal(payload: GoalCreate, db: Session = Depends(get_db)):
    # Goal creation is the entry point of the first closed loop: once the goal
    # is saved, Planner Agent immediately creates the first full schedule.
    daily_plans = await workflow.generate_plan(payload)
    return crud.create_goal_with_plan(db, payload, daily_plans)


@router.get("/goals/{goal_id}", response_model=GoalRead)
def read_goal(goal_id: int, db: Session = Depends(get_db)):
    goal = crud.get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Learning goal not found")
    return goal


@router.post("/plans/{plan_id}/tasks/generate", response_model=list[StudyTaskRead])
async def generate_daily_tasks(plan_id: int, db: Session = Depends(get_db)):
    plan = _get_plan_or_404(db, plan_id)
    tasks = await workflow.generate_tasks(_goal_payload(plan.goal), _plan_payload(plan))
    return crud.replace_tasks(db, plan.id, tasks)


@router.patch("/tasks/{task_id}/status", response_model=StudyTaskRead)
def update_task_status(
    task_id: int, payload: TaskStatusUpdate, db: Session = Depends(get_db)
):
    task = crud.update_task_status(db, task_id, payload.status)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/plans/{plan_id}/review", response_model=StudyReviewRead)
async def create_review(
    plan_id: int, payload: ReviewCreate, db: Session = Depends(get_db)
):
    plan = _get_plan_or_404(db, plan_id)
    tasks = crud.list_tasks(db, plan.id)

    if not tasks:
        generated = await workflow.generate_tasks(_goal_payload(plan.goal), _plan_payload(plan))
        tasks = crud.replace_tasks(db, plan.id, generated)

    task_payloads = [_task_payload(item) for item in tasks]
    review = await workflow.generate_review(
        _goal_payload(plan.goal),
        _plan_payload(plan),
        task_payloads,
        payload.feedback,
    )
    return crud.create_review(db, plan, review, payload.feedback)


@router.post("/goals/{goal_id}/adjust", response_model=PlanAdjustmentRead)
async def adjust_tomorrow_plan(
    goal_id: int, payload: AdjustmentRequest, db: Session = Depends(get_db)
):
    goal = crud.get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Learning goal not found")

    current_plan = crud.get_plan_by_day(db, goal_id, payload.from_day)
    tomorrow_plan = crud.get_plan_by_day(db, goal_id, payload.from_day + 1)
    if current_plan is None:
        raise HTTPException(status_code=404, detail="Current plan not found")
    if tomorrow_plan is None:
        raise HTTPException(status_code=400, detail="No tomorrow plan to adjust")

    review = crud.latest_review_for_plan(db, current_plan.id)
    if review is None:
        raise HTTPException(status_code=400, detail="Create a review before adjustment")

    adjustment = await workflow.adjust_tomorrow_plan(
        _goal_payload(goal),
        _plan_payload(tomorrow_plan),
        _review_payload(review),
    )
    return crud.apply_adjustment(
        db,
        goal_id=goal.id,
        from_day=payload.from_day,
        tomorrow_plan=tomorrow_plan,
        adjustment=adjustment,
    )


def _get_plan_or_404(db: Session, plan_id: int) -> models.StudyPlan:
    plan = crud.get_plan(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Study plan not found")
    return plan


def _goal_payload(goal: models.LearningGoal) -> dict:
    return {
        "id": goal.id,
        "title": goal.title,
        "exam_date": goal.exam_date,
        "daily_minutes": goal.daily_minutes,
        "current_level": goal.current_level,
        "key_topics": goal.key_topics,
    }


def _plan_payload(plan: models.StudyPlan) -> dict:
    return {
        "id": plan.id,
        "day_index": plan.day_index,
        "plan_date": plan.plan_date,
        "topic": plan.topic,
        "objective": plan.objective,
    }


def _task_payload(task: models.StudyTask) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "estimated_minutes": task.estimated_minutes,
        "task_type": task.task_type,
        "status": task.status,
    }


def _review_payload(review: models.StudyReview) -> dict:
    return {
        "completion_rate": review.completion_rate,
        "summary": review.summary,
        "weak_points": review.weak_points,
        "suggestions": review.suggestions,
    }

