from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GoalCreate(BaseModel):
    """创建学习目标的请求体。"""

    title: str = Field(min_length=2, max_length=200)
    # exam: 期末/考研等有明确考试日期；duration: 没有考试日期，只按固定周期学习。
    goal_type: Literal["exam", "duration"] = "exam"
    exam_date: date | None = None
    duration_days: int | None = Field(default=None, ge=3, le=120)
    daily_minutes: int = Field(ge=30, le=600)
    current_level: str = Field(min_length=1, max_length=40)
    key_topics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_goal_timing(self) -> "GoalCreate":
        """校验两种目标模式所需的时间字段。"""

        if self.goal_type == "exam" and self.exam_date is None:
            raise ValueError("考试模式需要提供 exam_date")
        if self.goal_type == "duration" and self.duration_days is None:
            raise ValueError("固定周期模式需要提供 duration_days")
        return self

    @property
    def resolved_exam_date(self) -> date:
        """返回可落库的目标结束日期。

        旧表结构和列表页仍然依赖 `exam_date` 字段。对于固定周期学习，
        这里把它解释为“计划结束日期”，从而兼容既有查询和展示逻辑。
        """

        if self.exam_date is not None:
            return self.exam_date
        return date.today() + timedelta(days=max(self.duration_days or 1, 1) - 1)


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
    goal_type: Literal["exam", "duration"] = "exam"
    exam_date: date
    duration_days: int | None = None
    daily_minutes: int
    current_level: str
    key_topics: list[str]
    plans: list[StudyPlanRead] = []


class GoalSummaryRead(BaseModel):
    """学习目标列表页使用的轻量摘要。"""

    id: int
    title: str
    goal_type: Literal["exam", "duration"] = "exam"
    exam_date: date
    duration_days: int | None = None
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
    ocr_provider: str | None = None
    ocr_enabled: bool = False
    ocr_model: str | None = None
    ocr_endpoint: str | None = None
    ok: bool
    reply: str | None = None
    error: str | None = None


class ChatMessage(BaseModel):
    """聊天抽屉中的单条消息。"""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=24000)


class ChatCompressMessage(BaseModel):
    """用于压缩历史上下文的聊天消息，允许接收更长的旧回复。"""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=60000)


class ReadingContext(BaseModel):
    """前端资料阅读器传给聊天助手的当前 PDF 页上下文。"""

    material_id: int
    page_index: int = Field(ge=1)


class ChatStreamRequest(BaseModel):
    """流式聊天接口的请求体。"""

    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    goal_id: int | None = None
    plan_id: int | None = None
    reading_context: ReadingContext | None = None


class ChatCompressRequest(BaseModel):
    """请求把较长的聊天历史压缩成一条摘要上下文。"""

    messages: list[ChatCompressMessage] = Field(min_length=1, max_length=20)
    target_chars: int = Field(default=6000, ge=1000, le=12000)


class ChatCompressResponse(BaseModel):
    """聊天历史压缩结果。"""

    message: ChatMessage
    compressed: bool = True
    original_chars: int


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
    outline_json: list[dict] | None = None
    outline_status: str | None = None
    outline_source: str | None = None


class MaterialPdfMetaRead(BaseModel):
    """PDF 阅读器打开资料时需要的基础元信息。"""

    material_id: int
    filename: str
    page_count: int
    readable_pages: list[int]


class MaterialPdfPageTextRead(BaseModel):
    """PDF 单页文本提取结果。"""

    material_id: int
    filename: str
    page_index: int
    readable: bool
    text: str
    text_hash: str


class PdfPageTranslateRequest(BaseModel):
    """请求翻译 PDF 当前页。"""

    target_language: str = Field(default="zh-CN", max_length=20)
    mode: Literal["text", "ocr"] = "text"


class PdfPageTranslationRead(BaseModel):
    """PDF 单页翻译响应。"""

    material_id: int
    page_index: int
    source_lang: str
    target_lang: str
    text_hash: str
    translated_text: str
    extraction_mode: Literal["text", "ocr"] = "text"
    cached: bool


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
    rerank_score: float | None = None
    lexical_score: float | None = None
    retrieval_source: str | None = None


class KnowledgeSearchResponse(BaseModel):
    """Chroma 知识库检索的响应结构。"""

    goal_id: int
    collection: str
    query: str
    hits: list[KnowledgeSearchHit]
