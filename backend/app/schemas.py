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


class GoalSummaryRead(BaseModel):
    """学习目标列表页使用的轻量摘要。"""

    id: int
    title: str
    exam_date: date
    daily_minutes: int
    current_level: str
    key_topics: list[str]
    status: str
    plan_count: int
    material_count: int
    created_at: datetime
    updated_at: datetime


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


class QuizGenerateRequest(BaseModel):
    """生成任务小测的请求体。

    默认复用已生成的小测，避免用户反复打开弹窗时重复消耗 LLM 调用。
    """

    regenerate: bool = False


class QuizQuestion(BaseModel):
    """任务小测中的单道题。"""

    id: str
    type: Literal["single_choice", "short_answer"]
    question: str
    options: list[str] = Field(default_factory=list)
    correct_answer: str | None = None
    reference_answer: str | None = None
    explanation: str = ""


class QuizAnswerItem(BaseModel):
    """用户提交的单题答案。"""

    question_id: str
    answer: str = ""


class QuizSubmitRequest(BaseModel):
    """提交任务小测答案的请求体。"""

    answers: list[QuizAnswerItem] = Field(default_factory=list)


class QuizResultItem(BaseModel):
    """单题批改结果。"""

    question_id: str
    is_correct: bool
    score: int = Field(ge=0, le=100)
    feedback: str
    correct_answer: str | None = None


class QuizResultRead(BaseModel):
    """任务小测的整体批改结果。"""

    score: int = Field(ge=0, le=100)
    items: list[QuizResultItem]
    summary: str


class TaskQuizRead(BaseModel):
    """任务小测详情。"""

    id: int
    task_id: int
    plan_id: int
    goal_id: int
    status: str
    source_mode: Literal["rag", "llm_fallback"]
    questions: list[QuizQuestion]
    answers: list[QuizAnswerItem] = Field(default_factory=list)
    result: QuizResultRead | None = None
    created_at: datetime
    submitted_at: datetime | None = None


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


class ChatMessage(BaseModel):
    """聊天抽屉中的单条消息。"""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)


class ChatStreamRequest(BaseModel):
    """流式聊天接口的请求体。"""

    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    goal_id: int | None = None
    plan_id: int | None = None


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
    material_id: int | None = None
    plan_id: int | None = None
    day_index: int | None = Field(default=None, ge=1)
    source_type: str | None = Field(default=None, max_length=40)


class KnowledgeSnippetCreate(BaseModel):
    """手动写入 RAG 知识库的资料片段。"""

    content: str = Field(min_length=1, max_length=12000)
    source_name: str = Field(default="手动补充", min_length=1, max_length=200)
    plan_id: int | None = None
    day_index: int | None = Field(default=None, ge=1)


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
