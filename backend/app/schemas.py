from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GoalCreate(BaseModel):
    """创建学习目标的请求体。"""

    title: str = Field(min_length=2, max_length=200)
    exam_date: date
    daily_minutes: int = Field(ge=30, le=600)
    current_level: str = Field(min_length=1, max_length=40)
    key_topics: list[str] = Field(default_factory=list)


class JobRead(BaseModel):
    """后台异步任务的响应结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    goal_id: int | None = None
    job_type: str
    status: str
    progress: int
    result_json: dict | None = None
    error_message: str | None = None
    finished_at: datetime | None = None


class StudyPlanRead(BaseModel):
    """单个每日计划的响应结构。"""

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
    """学习目标及其时间线的响应结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    exam_date: date
    daily_minutes: int
    current_level: str
    key_topics: list[str]
    plans: list[StudyPlanRead] = []


class StudyTaskRead(BaseModel):
    """单个任务卡片的响应结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    estimated_minutes: int
    task_type: str
    status: str


class TaskStatusUpdate(BaseModel):
    """更新任务状态的请求体。"""

    status: Literal["pending", "partial", "done", "missed"]


class ReviewCreate(BaseModel):
    """生成每日复盘的请求体。"""

    feedback: str = ""


class StudyReviewRead(BaseModel):
    """Review Agent 输出的响应结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    completion_rate: float
    summary: str
    weak_points: list[str]
    suggestions: list[str]


class AdjustmentRequest(BaseModel):
    """基于某一天复盘结果调整计划的请求体。"""

    from_day: int = Field(ge=1)


class PlanAdjustmentRead(BaseModel):
    """计划调整结果的响应结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    from_day: int
    original_topic: str
    adjusted_topic: str
    original_objective: str
    adjusted_objective: str
    reason: str


class LLMHealthRead(BaseModel):
    """DeepSeek 连通性检查的响应结构。"""

    configured: bool
    provider: str
    model: str
    ok: bool
    reply: str | None = None
    error: str | None = None


class CourseMaterialRead(BaseModel):
    """上传课程资料元数据的响应结构。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    goal_id: int
    filename: str
    file_type: str
    parse_status: str
    error_message: str | None = None
    chunk_count: int
    chroma_collection: str


class KnowledgeSearchRequest(BaseModel):
    """检索某个目标 Chroma 知识库的请求体。"""

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


class KnowledgeSearchHit(BaseModel):
    """单条规范化后的 Chroma 检索结果。"""

    content: str
    metadata: dict
    distance: float | None = None


class KnowledgeSearchResponse(BaseModel):
    """Chroma 知识库检索的响应结构。"""

    goal_id: int
    collection: str
    query: str
    hits: list[KnowledgeSearchHit]
