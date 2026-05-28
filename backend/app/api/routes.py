from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app import crud, models
from app.agents import workflow
from app.agents.llm import DeepSeekClient
from app.db.session import get_db
from app.schemas import (
    AdjustmentRequest,
    CourseMaterialRead,
    GoalCreate,
    GoalRead,
    JobRead,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    LLMHealthRead,
    PlanAdjustmentRead,
    ReviewCreate,
    StudyReviewRead,
    StudyTaskRead,
    TaskStatusUpdate,
)
from app.services.knowledge_base import ChromaKnowledgeBase, collection_name_for_goal
from app.services.material_pipeline import build_material_knowledge_base
from app.services.materials import save_upload_file
from app.tasks.jobs import generate_goal_plan_task, parse_material_task

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health_check() -> dict[str, str]:
    """轻量级健康检查接口，用于本地测试和 Docker 探活。"""

    return {"status": "ok"}


@router.get("/llm/health", response_model=LLMHealthRead)
async def llm_health_check():
    """检查 DeepSeek API Key 和接口地址是否可用。

    普通 Agent 请求在 LLM 不可用时会自动走规则兜底；这个接口更严格，
    用于开发阶段确认是否真的请求到了外部模型。
    """

    return await DeepSeekClient().health_check()


@router.post("/goals", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
async def create_goal(payload: GoalCreate, db: Session = Depends(get_db)):
    """创建学习目标，并立即生成学习时间线。

    这是产品核心闭环的入口。用户提交目标表单后，Planner Agent 生成每日计划，
    后端在同一个请求中保存目标和计划记录。
    """

    # 目标创建是第一版闭环入口：目标信息进入 Planner Agent 后会生成完整计划。
    daily_plans = await workflow.generate_plan(payload)
    return crud.create_goal_with_plan(db, payload, daily_plans)


@router.post(
    "/goals/async",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_goal_async(payload: GoalCreate, db: Session = Depends(get_db)):
    """异步创建学习目标，并把计划生成交给 Celery。

    接口立即返回 Job，前端可以轮询 `/jobs/{job_id}`。任务完成后，
    `result_json.goal_id` 对应的目标会拥有完整计划时间线。
    """

    goal = crud.create_goal_only(db, payload, status="planning")
    job = crud.create_job(
        db,
        job_type="generate_goal_plan",
        goal_id=goal.id,
        result_json={"goal_id": goal.id},
    )

    try:
        generate_goal_plan_task.delay(job.id, goal.id)
    except Exception as exc:
        job = crud.mark_job_failed(db, job, f"任务投递失败：{exc}")
    return job


@router.get("/goals/{goal_id}", response_model=GoalRead)
def read_goal(goal_id: int, db: Session = Depends(get_db)):
    """读取一个学习目标及其每日计划时间线。"""

    goal = crud.get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Learning goal not found")
    return goal


@router.post(
    "/goals/{goal_id}/materials/upload",
    response_model=CourseMaterialRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_course_material(
    goal_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传、解析、切分课程资料，并写入 Chroma 知识库。

    当前版本采用同步处理，便于第一版 Chroma 功能演示：接口返回时已经包含
    最终解析状态和 chunk 数量。解析/建库逻辑被集中放在一个代码块中，
    后续迁移到 Celery 异步任务时可以尽量少改接口契约。
    """

    _get_goal_or_404(db, goal_id)

    try:
        storage_path, filename, file_type = save_upload_file(file, goal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    material = crud.create_course_material(
        db,
        goal_id=goal_id,
        filename=filename,
        file_type=file_type,
        storage_path=storage_path,
        chroma_collection=collection_name_for_goal(goal_id),
    )

    try:
        return build_material_knowledge_base(db, material)
    except Exception as exc:
        return crud.mark_material_failed(db, material, str(exc))


@router.post(
    "/goals/{goal_id}/materials/upload/async",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_course_material_async(
    goal_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """异步上传课程资料，并把解析/建库交给 Celery。

    同步上传接口适合小文件和快速 Demo；这个接口适合 PDF/PPT 等较大文件。
    返回的 Job 中会带上 `material_id`，前端可用 job 查询进度，也可以查询资料状态。
    """

    _get_goal_or_404(db, goal_id)
    try:
        storage_path, filename, file_type = save_upload_file(file, goal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    material = crud.create_course_material(
        db,
        goal_id=goal_id,
        filename=filename,
        file_type=file_type,
        storage_path=storage_path,
        chroma_collection=collection_name_for_goal(goal_id),
    )
    job = crud.create_job(
        db,
        job_type="parse_material",
        goal_id=goal_id,
        result_json={"material_id": material.id},
    )

    try:
        parse_material_task.delay(job.id, material.id)
    except Exception as exc:
        crud.mark_material_failed(db, material, f"任务投递失败：{exc}")
        job = crud.mark_job_failed(db, job, f"任务投递失败：{exc}")
    return job


@router.get("/goals/{goal_id}/materials", response_model=list[CourseMaterialRead])
def list_course_materials(goal_id: int, db: Session = Depends(get_db)):
    """列出某个学习目标关联的所有上传资料。"""

    _get_goal_or_404(db, goal_id)
    return crud.list_materials(db, goal_id)


@router.get("/materials/{material_id}", response_model=CourseMaterialRead)
def read_course_material(material_id: int, db: Session = Depends(get_db)):
    """根据 id 读取单个课程资料元数据。"""

    material = crud.get_material(db, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Course material not found")
    return material


@router.get("/jobs/{job_id}", response_model=JobRead)
def read_job(job_id: int, db: Session = Depends(get_db)):
    """查询后台任务状态。

    前端通过这个接口轮询异步任务进度。状态一般为：
    pending、running、success、failed。
    """

    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post(
    "/goals/{goal_id}/knowledge/search",
    response_model=KnowledgeSearchResponse,
)
def search_goal_knowledge(
    goal_id: int,
    payload: KnowledgeSearchRequest,
    db: Session = Depends(get_db),
):
    """检索某个学习目标对应的 Chroma 知识库。"""

    _get_goal_or_404(db, goal_id)
    hits = ChromaKnowledgeBase().query(goal_id, payload.query, payload.top_k)
    return {
        "goal_id": goal_id,
        "collection": collection_name_for_goal(goal_id),
        "query": payload.query,
        "hits": hits,
    }


@router.post("/plans/{plan_id}/tasks/generate", response_model=list[StudyTaskRead])
async def generate_daily_tasks(plan_id: int, db: Session = Depends(get_db)):
    """为某一天计划生成可执行任务卡片。

    调用 Task Agent 之前，会先用当天主题从 Chroma 检索少量课程资料上下文。
    如果还没有上传资料或建库失败，流程仍然会像 v0.1 一样正常生成任务。
    """

    plan = _get_plan_or_404(db, plan_id)
    daily_plan = _plan_payload(plan)
    daily_plan["knowledge_context"] = _knowledge_context_for_plan(plan)
    tasks = await workflow.generate_tasks(_goal_payload(plan.goal), daily_plan)
    return crud.replace_tasks(db, plan.id, tasks)


@router.patch("/tasks/{task_id}/status", response_model=StudyTaskRead)
def update_task_status(
    task_id: int, payload: TaskStatusUpdate, db: Session = Depends(get_db)
):
    """更新前端任务看板中的任务打卡状态。"""

    task = crud.update_task_status(db, task_id, payload.status)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/plans/{plan_id}/review", response_model=StudyReviewRead)
async def create_review(
    plan_id: int, payload: ReviewCreate, db: Session = Depends(get_db)
):
    """生成并保存当天学习复盘。

    如果用户还没生成今日任务就直接复盘，接口会先生成任务，确保 Review Agent
    一定有任务状态作为输入。
    """

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
    """根据最新复盘结果调整下一天计划。

    这是“学习执行官”的关键能力：把复盘信号转化为明日计划调整，
    并保存调整前后的对比信息。
    """

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
    """读取计划；不存在时抛出 FastAPI 404。"""

    plan = crud.get_plan(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Study plan not found")
    return plan


def _get_goal_or_404(db: Session, goal_id: int) -> models.LearningGoal:
    """读取学习目标；不存在时抛出 FastAPI 404。"""

    goal = crud.get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Learning goal not found")
    return goal


def _goal_payload(goal: models.LearningGoal) -> dict:
    """把学习目标 ORM 对象转换成 Agent 需要的字典格式。"""

    return {
        "id": goal.id,
        "title": goal.title,
        "exam_date": goal.exam_date,
        "daily_minutes": goal.daily_minutes,
        "current_level": goal.current_level,
        "key_topics": goal.key_topics,
    }


def _plan_payload(plan: models.StudyPlan) -> dict:
    """把每日计划 ORM 对象转换成 Agent 需要的字典格式。"""

    return {
        "id": plan.id,
        "day_index": plan.day_index,
        "plan_date": plan.plan_date,
        "topic": plan.topic,
        "objective": plan.objective,
    }


def _task_payload(task: models.StudyTask) -> dict:
    """把任务 ORM 对象转换成 Review Agent 需要的字典格式。"""

    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "estimated_minutes": task.estimated_minutes,
        "task_type": task.task_type,
        "status": task.status,
    }


def _review_payload(review: models.StudyReview) -> dict:
    """把复盘 ORM 对象转换成 Adjust Agent 需要的字典格式。"""

    return {
        "completion_rate": review.completion_rate,
        "summary": review.summary,
        "weak_points": review.weak_points,
        "suggestions": review.suggestions,
    }


def _knowledge_context_for_plan(plan: models.StudyPlan) -> list[dict]:
    """为 Task Agent 检索少量课程资料上下文。

    Chroma 异常不应该阻塞普通任务生成；如果还没有资料建库，
    Agent 会退回到第一版的生成方式。
    """

    try:
        return ChromaKnowledgeBase().query(plan.goal_id, plan.topic, top_k=3)
    except Exception:
        return []
