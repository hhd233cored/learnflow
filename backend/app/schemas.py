from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GoalCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    exam_date: date
    daily_minutes: int = Field(ge=30, le=600)
    current_level: str = Field(min_length=1, max_length=40)
    key_topics: list[str] = Field(default_factory=list)


class StudyPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    day_index: int
    plan_date: date
    topic: str
    objective: str
    status: str
    adjusted: bool
    adjustment_reason: str | None = None


class GoalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    exam_date: date
    daily_minutes: int
    current_level: str
    key_topics: list[str]
    plans: list[StudyPlanRead] = []


class StudyTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    estimated_minutes: int
    task_type: str
    status: str


class TaskStatusUpdate(BaseModel):
    status: Literal["pending", "partial", "done", "missed"]


class ReviewCreate(BaseModel):
    feedback: str = ""


class StudyReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    completion_rate: float
    summary: str
    weak_points: list[str]
    suggestions: list[str]


class AdjustmentRequest(BaseModel):
    from_day: int = Field(ge=1)


class PlanAdjustmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_day: int
    original_topic: str
    adjusted_topic: str
    original_objective: str
    adjusted_objective: str
    reason: str

