from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


def json_column():
    """在 PostgreSQL 中使用 JSONB，在本地 SQLite 中使用普通 JSON。

    应用同时支持 Docker/PostgreSQL 和本地 SQLite。SQLAlchemy variant
    让两种运行环境可以复用同一份模型定义。
    """

    return JSON().with_variant(JSONB, "postgresql")


class TimestampMixin:
    """所有持久化模型可复用的创建/更新时间字段。"""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class LearningGoal(TimestampMixin, Base):
    """用户的长期学习目标。

    例如：“10 天复习操作系统”。每个目标拥有自己的每日计划、复盘记录、
    计划调整记录和上传的课程资料。
    """

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
    materials: Mapped[list["CourseMaterial"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class StudyPlan(TimestampMixin, Base):
    """生成出来的学习时间线中的某一天计划。"""

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
    """某一天计划下的一张可执行任务卡片。"""

    __tablename__ = "study_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plans.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")

    plan: Mapped[StudyPlan] = relationship(back_populates="tasks")
    quizzes: Mapped[list["TaskQuiz"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskQuiz(TimestampMixin, Base):
    """某个学习任务对应的轻量级小测。

    Demo 版不拆题库、答案、批改明细多张表，而是把 3 道题、用户答案和批改结果
    存成 JSON。这样接口和前端实现更轻，后续如果要做正式题库再迁移成规范表结构。
    """

    __tablename__ = "task_quizzes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("study_tasks.id"), nullable=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plans.id"), nullable=False)
    goal_id: Mapped[int] = mapped_column(ForeignKey("learning_goals.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="generated")
    source_mode: Mapped[str] = mapped_column(String(30), default="llm_fallback")
    questions_json: Mapped[list[dict]] = mapped_column(
        MutableList.as_mutable(json_column())
    )
    answers_json: Mapped[list[dict] | None] = mapped_column(
        MutableList.as_mutable(json_column()), nullable=True
    )
    result_json: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(json_column()), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    task: Mapped[StudyTask] = relationship(back_populates="quizzes")


class StudyReview(TimestampMixin, Base):
    """Review Agent 对某一天学习情况生成的复盘结果。"""

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
    """Adjust Agent 修改未来计划时留下的审计记录。"""

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


class CourseMaterial(TimestampMixin, Base):
    """上传课程资料文件的元数据。

    原始文件存放在磁盘上，向量化后的 chunk 存放在 Chroma 中；
    这张表负责追踪状态，并连接文件系统与向量库。
    """

    __tablename__ = "course_materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("learning_goals.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(30), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    chroma_collection: Mapped[str] = mapped_column(String(120), nullable=False)

    goal: Mapped[LearningGoal] = relationship(back_populates="materials")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="material", cascade="all, delete-orphan"
    )


class DocumentChunk(TimestampMixin, Base):
    """一个已写入 Chroma 的文档 chunk 在关系型数据库中的元数据。"""

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    material_id: Mapped[int] = mapped_column(
        ForeignKey("course_materials.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_preview: Mapped[str] = mapped_column(Text, nullable=False)
    chroma_collection: Mapped[str] = mapped_column(String(120), nullable=False)
    chroma_document_id: Mapped[str] = mapped_column(String(120), nullable=False)

    material: Mapped[CourseMaterial] = relationship(back_populates="chunks")


class Job(TimestampMixin, Base):
    """后台异步任务记录。

    Celery 负责真正执行耗时任务，数据库中的 Job 用来给前端轮询状态。
    这样用户可以知道资料解析、Chroma 建库、长计划生成等任务是否完成。
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    goal_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_goals.id"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(json_column()), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    goal: Mapped[LearningGoal | None] = relationship(back_populates="jobs")
