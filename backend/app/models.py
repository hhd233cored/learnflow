from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


def json_column():
    """Use JSONB on PostgreSQL and plain JSON on SQLite/local development."""

    return JSON().with_variant(JSONB, "postgresql")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class LearningGoal(TimestampMixin, Base):
    __tablename__ = "learning_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    exam_date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    current_level: Mapped[str] = mapped_column(String(40), nullable=False)
    key_topics: Mapped[list[str]] = mapped_column(MutableList.as_mutable(json_column()))
    status: Mapped[str] = mapped_column(String(30), default="active")

    plans: Mapped[list["StudyPlan"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan", order_by="StudyPlan.day_index"
    )
    reviews: Mapped[list["StudyReview"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )
    adjustments: Mapped[list["PlanAdjustment"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class StudyPlan(TimestampMixin, Base):
    __tablename__ = "study_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("learning_goals.id"), nullable=False)
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="planned")
    adjusted: Mapped[bool] = mapped_column(Boolean, default=False)
    adjustment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    goal: Mapped[LearningGoal] = relationship(back_populates="plans")
    tasks: Mapped[list["StudyTask"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["StudyReview"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class StudyTask(TimestampMixin, Base):
    __tablename__ = "study_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plans.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")

    plan: Mapped[StudyPlan] = relationship(back_populates="tasks")


class StudyReview(TimestampMixin, Base):
    __tablename__ = "study_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("learning_goals.id"), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plans.id"), nullable=False)
    completion_rate: Mapped[float] = mapped_column(nullable=False)
    weak_points: Mapped[list[str]] = mapped_column(MutableList.as_mutable(json_column()))
    suggestions: Mapped[list[str]] = mapped_column(MutableList.as_mutable(json_column()))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    feedback: Mapped[str] = mapped_column(Text, default="")

    goal: Mapped[LearningGoal] = relationship(back_populates="reviews")
    plan: Mapped[StudyPlan] = relationship(back_populates="reviews")


class PlanAdjustment(TimestampMixin, Base):
    __tablename__ = "plan_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("learning_goals.id"), nullable=False)
    from_day: Mapped[int] = mapped_column(Integer, nullable=False)
    original_topic: Mapped[str] = mapped_column(String(200), nullable=False)
    adjusted_topic: Mapped[str] = mapped_column(String(200), nullable=False)
    original_objective: Mapped[str] = mapped_column(Text, nullable=False)
    adjusted_objective: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    goal: Mapped[LearningGoal] = relationship(back_populates="adjustments")

