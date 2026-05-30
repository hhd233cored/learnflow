from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import crud, models
from app.agents import workflow
from app.agents.llm import DeepSeekClient
from app.db.session import get_db
from app.schemas import (
    AdjustmentRequest,
    ChatStreamRequest,
    CourseMaterialRead,
    GoalCreate,
    GoalRead,
    GoalSummaryRead,
    JobRead,
    KnowledgeSnippetCreate,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    LLMHealthRead,
    PlanAdjustmentRead,
    QuizGenerateRequest,
    QuizSubmitRequest,
    ReviewCreate,
    StudyReviewRead,
    StudyTaskRead,
    TaskQuizRead,
    TaskStatusUpdate,
)
from app.core.config import get_settings
from app.services.chunking import split_text_into_chunks
from app.services.document_enrichment import enrich_chunks
from app.services.knowledge_base import ChromaKnowledgeBase, collection_name_for_goal
from app.services.material_pipeline import build_material_knowledge_base
from app.services.materials import save_upload_file
from app.services.quiz import generate_quiz_for_task, grade_quiz_answers
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


@router.post("/chat/stream")
async def stream_chat(payload: ChatStreamRequest, db: Session = Depends(get_db)):
    """AI 学习助手流式聊天接口。

    前端聊天抽屉会把历史消息、当前 goal 和当前 day 传进来。后端会补充
    学习目标、每日计划、任务状态和 Chroma 检索片段，再交给 DeepSeek
    以文本流形式返回。
    """

    tool_result = await _chat_tool_result(payload, db)
    context = _chat_context(payload, db)
    if tool_result:
        context = f"{context}\n\n已执行的工具结果：\n{tool_result}".strip()
    messages = [item.model_dump() for item in payload.messages[-12:]]
    fallback = (
        f"{tool_result}\n\n{_fallback_chat_reply(payload, context)}"
        if tool_result
        else _fallback_chat_reply(payload, context)
    )

    stream = DeepSeekClient().stream_chat(
        system_prompt=_chat_system_prompt(context),
        messages=messages,
        fallback=fallback,
    )
    return StreamingResponse(
        stream,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/goals", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
async def create_goal(payload: GoalCreate, db: Session = Depends(get_db)):
    """创建学习目标，并立即生成学习时间线。

    这是产品核心闭环的入口。用户提交目标表单后，Planner Agent 生成每日计划，
    后端在同一个请求中保存目标和计划记录。
    """

    # 目标创建是第一版闭环入口：目标信息进入 Planner Agent 后会生成完整计划。
    daily_plans = await workflow.generate_plan(payload)
    return crud.create_goal_with_plan(db, payload, daily_plans)


@router.get("/goals", response_model=list[GoalSummaryRead])
def list_goals(db: Session = Depends(get_db)):
    """列出历史学习计划摘要，供前端恢复和切换计划。"""

    return crud.list_goal_summaries(db)


@router.post(
    "/goals/with-materials",
    response_model=GoalRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_goal_with_materials(
    title: str = Form(...),
    exam_date: date = Form(...),
    daily_minutes: int = Form(...),
    current_level: str = Form(...),
    key_topics: str = Form(""),
    files: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
):
    """创建学习目标，并在生成计划前先处理上传资料。

    这个接口服务于“目标输入 + 课程资料上传 + 生成计划”的一体化流程：
    先创建 goal 获得 id，再把 PDF/PPT/Word 等资料写入该 goal 的 Chroma
    collection，最后把检索到的资料上下文交给 Planner Agent 生成总计划。
    """

    payload = GoalCreate(
        title=title,
        exam_date=exam_date,
        daily_minutes=daily_minutes,
        current_level=current_level,
        key_topics=_parse_key_topics(key_topics),
    )
    goal = crud.create_goal_only(db, payload, status="planning")

    for upload in files or []:
        if not upload.filename:
            continue
        material = None
        try:
            storage_path, filename, file_type = save_upload_file(upload, goal.id)
            material = crud.create_course_material(
                db,
                goal_id=goal.id,
                filename=filename,
                file_type=file_type,
                storage_path=storage_path,
                chroma_collection=collection_name_for_goal(goal.id),
            )
            await build_material_knowledge_base(db, material)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            # 单个资料解析失败不阻塞计划生成；失败信息会保存在资料记录中。
            if material is not None:
                crud.mark_material_failed(db, material, str(exc))

    knowledge_context = _knowledge_context_for_goal(goal.id, payload)
    daily_plans = await workflow.generate_plan(payload, knowledge_context)
    return crud.replace_goal_plans(db, goal, daily_plans)


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


@router.post("/goals/{goal_id}/plans/regenerate", response_model=GoalRead)
async def regenerate_goal_plan(goal_id: int, db: Session = Depends(get_db)):
    """基于当前目标信息和最新 RAG 知识库重新生成整套学习计划。"""

    goal = _get_goal_or_404(db, goal_id)
    payload = GoalCreate(
        title=goal.title,
        exam_date=goal.exam_date,
        daily_minutes=goal.daily_minutes,
        current_level=goal.current_level,
        key_topics=goal.key_topics,
    )
    knowledge_context = _knowledge_context_for_goal(goal.id, payload)
    daily_plans = await workflow.generate_plan(payload, knowledge_context)
    return crud.replace_goal_plans(db, goal, daily_plans)


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: int, db: Session = Depends(get_db)):
    """删除某个学习目标及其计划、任务、复盘和知识库 collection。"""

    deleted = crud.delete_goal(db, goal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Learning goal not found")
    ChromaKnowledgeBase().delete_goal_collection(goal_id)
    return None


@router.post(
    "/goals/{goal_id}/materials/upload",
    response_model=CourseMaterialRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_course_material(
    goal_id: int,
    plan_id: int | None = Form(default=None),
    day_index: int | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传、解析、切分课程资料，并写入 Chroma 知识库。

    当前版本采用同步处理，便于第一版 Chroma 功能演示：接口返回时已经包含
    最终解析状态和 chunk 数量。解析/建库逻辑被集中放在一个代码块中，
    后续迁移到 Celery 异步任务时可以尽量少改接口契约。
    """

    _get_goal_or_404(db, goal_id)
    scope_plan_id, scope_day_index = _resolve_plan_scope(
        db, goal_id, plan_id, day_index
    )

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
        return await build_material_knowledge_base(
            db,
            material,
            plan_id=scope_plan_id,
            day_index=scope_day_index,
        )
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
    hits = ChromaKnowledgeBase().query(
        goal_id,
        payload.query,
        payload.top_k,
        material_id=payload.material_id,
        plan_id=payload.plan_id,
        day_index=payload.day_index,
        source_type=payload.source_type,
    )
    return {
        "goal_id": goal_id,
        "collection": collection_name_for_goal(goal_id),
        "query": payload.query,
        "hits": hits,
    }


@router.post(
    "/goals/{goal_id}/knowledge/snippets",
    response_model=CourseMaterialRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_snippet(
    goal_id: int,
    payload: KnowledgeSnippetCreate,
    db: Session = Depends(get_db),
):
    """把用户手动补充的知识片段写入目标级 Chroma 知识库。"""

    return await _create_manual_knowledge_material(
        db,
        goal_id=goal_id,
        content=payload.content,
        source_name=payload.source_name,
        plan_id=payload.plan_id,
        day_index=payload.day_index,
    )


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


@router.get("/plans/{plan_id}/tasks", response_model=list[StudyTaskRead])
def list_daily_tasks(plan_id: int, db: Session = Depends(get_db)):
    """读取某一天已经生成过的任务卡片。

    前端切换到任意 Day 时会先调用这个接口。如果返回空列表，
    再按需调用生成接口，避免用户只是查看计划时重复覆盖已有任务。
    """

    _get_plan_or_404(db, plan_id)
    return crud.list_tasks(db, plan_id)


@router.patch("/tasks/{task_id}/status", response_model=StudyTaskRead)
def update_task_status(
    task_id: int, payload: TaskStatusUpdate, db: Session = Depends(get_db)
):
    """更新前端任务看板中的任务打卡状态。"""

    task = crud.update_task_status(db, task_id, payload.status)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/tasks/{task_id}/quiz", response_model=TaskQuizRead)
async def generate_task_quiz(
    task_id: int,
    payload: QuizGenerateRequest | None = None,
    db: Session = Depends(get_db),
):
    """为某个任务生成或复用 3 道小测题。

    接口优先复用最近一次小测，避免用户反复打开弹窗时重复生成；需要重新出题时，
    前端可以传入 `{"regenerate": true}`。
    """

    request = payload or QuizGenerateRequest()
    task = crud.get_task_with_context(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    existing = crud.latest_quiz_for_task(db, task_id)
    if existing is not None and not request.regenerate:
        return _quiz_payload(existing)

    generated = await generate_quiz_for_task(task)
    quiz = crud.create_task_quiz(
        db,
        task=task,
        questions=generated["questions"],
        source_mode=generated["source_mode"],
    )
    return _quiz_payload(quiz)


@router.get("/tasks/{task_id}/quiz", response_model=TaskQuizRead)
def read_task_quiz(task_id: int, db: Session = Depends(get_db)):
    """读取某个任务最近一次生成的小测。"""

    quiz = crud.latest_quiz_for_task(db, task_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Task quiz not found")
    return _quiz_payload(quiz)


@router.post("/quizzes/{quiz_id}/submit", response_model=TaskQuizRead)
async def submit_task_quiz(
    quiz_id: int,
    payload: QuizSubmitRequest,
    db: Session = Depends(get_db),
):
    """提交任务小测答案并返回基础批改结果。"""

    quiz = crud.get_quiz(db, quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Task quiz not found")

    answers = [item.model_dump() for item in payload.answers]
    result = await grade_quiz_answers(quiz.questions_json, answers)
    updated = crud.submit_task_quiz(db, quiz, answers, result)
    return _quiz_payload(updated)


@router.post("/plans/{plan_id}/review", response_model=StudyReviewRead)
async def create_review(
    plan_id: int, payload: ReviewCreate, db: Session = Depends(get_db)
):
    """生成并保存当天学习复盘。

    如果用户还没生成今日任务就直接复盘，接口会先生成任务，确保 Review Agent
    一定有任务状态作为输入。
    """

    plan = _get_plan_or_404(db, plan_id)
    return await _create_review_for_plan(db, plan, payload.feedback)


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
    if current_plan is None:
        raise HTTPException(status_code=404, detail="Current plan not found")
    return await _adjust_after_plan(db, goal, current_plan)


async def _create_review_for_plan(
    db: Session, plan: models.StudyPlan, feedback: str
) -> models.StudyReview:
    """生成并保存某一天的复盘，供 API 和聊天工具复用。"""

    tasks = crud.list_tasks(db, plan.id)
    if not tasks:
        generated = await workflow.generate_tasks(_goal_payload(plan.goal), _plan_payload(plan))
        tasks = crud.replace_tasks(db, plan.id, generated)

    task_payloads = [_task_payload(item) for item in tasks]
    review = await workflow.generate_review(
        _goal_payload(plan.goal),
        _plan_payload(plan),
        task_payloads,
        feedback,
    )
    return crud.create_review(db, plan, review, feedback)


async def _adjust_after_plan(
    db: Session, goal: models.LearningGoal, current_plan: models.StudyPlan
) -> models.PlanAdjustment:
    """根据当前 Day 的最新复盘调整下一天计划。"""

    tomorrow_plan = crud.get_plan_by_day(db, goal.id, current_plan.day_index + 1)
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
        from_day=current_plan.day_index,
        tomorrow_plan=tomorrow_plan,
        adjustment=adjustment,
    )


async def _create_manual_knowledge_material(
    db: Session,
    goal_id: int,
    content: str,
    source_name: str,
    plan_id: int | None = None,
    day_index: int | None = None,
) -> models.CourseMaterial:
    """把手动输入的知识片段作为一种 manual 素材写入 Chroma。"""

    _get_goal_or_404(db, goal_id)
    scope_plan_id, scope_day_index = _resolve_plan_scope(
        db, goal_id, plan_id, day_index
    )
    settings = get_settings()
    chunks = split_text_into_chunks(
        content,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    if not chunks:
        raise HTTPException(status_code=400, detail="No readable text in snippet")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    material = crud.create_course_material(
        db,
        goal_id=goal_id,
        filename=source_name,
        file_type="manual",
        storage_path=f"manual://goal/{goal_id}/{timestamp}",
        chroma_collection=collection_name_for_goal(goal_id),
    )
    try:
        crud.mark_material_processing(db, material)
        enriched_chunks = await enrich_chunks(chunks, source_name)
        chroma_ids = ChromaKnowledgeBase().upsert_chunks(
            goal_id=goal_id,
            material_id=material.id,
            filename=source_name,
            chunks=chunks,
            enrichments=enriched_chunks,
            plan_id=scope_plan_id,
            day_index=scope_day_index,
            source_type="manual",
        )
        return crud.replace_material_chunks(db, material, chunks, chroma_ids)
    except Exception as exc:
        return crud.mark_material_failed(db, material, str(exc))


def _resolve_plan_scope(
    db: Session,
    goal_id: int,
    plan_id: int | None = None,
    day_index: int | None = None,
) -> tuple[int | None, int | None]:
    """校验上传/插入时选择的计划范围，并返回写入 Chroma 的 metadata。"""

    if plan_id is not None:
        plan = crud.get_plan(db, plan_id)
        if plan is None or plan.goal_id != goal_id:
            raise HTTPException(status_code=400, detail="Plan does not belong to goal")
        return plan.id, plan.day_index

    if day_index is not None:
        plan = crud.get_plan_by_day(db, goal_id, day_index)
        if plan is None:
            raise HTTPException(status_code=400, detail="Plan day not found")
        return plan.id, plan.day_index

    return None, None


async def _chat_tool_result(payload: ChatStreamRequest, db: Session) -> str | None:
    """根据用户自然语言触发轻量工具，并把工具结果放回聊天上下文。"""

    message = _last_user_message(payload)
    if not message or payload.goal_id is None:
        return None

    goal = crud.get_goal(db, payload.goal_id)
    plan = crud.get_plan(db, payload.plan_id) if payload.plan_id else None
    if goal is None:
        return None

    try:
        if _wants_knowledge_insert(message):
            content = _extract_snippet_content(message)
            material = await _create_manual_knowledge_material(
                db,
                goal_id=goal.id,
                content=content,
                source_name="聊天补充",
                plan_id=plan.id if plan else None,
            )
            return (
                "KnowledgeIngestTool 已执行："
                f"已写入 {material.chunk_count} 个知识片段到 {material.chroma_collection}。"
            )

        if plan is not None and _wants_adjustment(message):
            if crud.latest_review_for_plan(db, plan.id) is None:
                await _create_review_for_plan(db, plan, message)
            adjustment = await _adjust_after_plan(db, goal, plan)
            return (
                "ReviewTool 与 AdjustPlanTool 已执行："
                f"Day {adjustment.from_day + 1} 已调整为「{adjustment.adjusted_topic}」。"
                f"原因：{adjustment.reason}"
            )

        if plan is not None and _wants_review(message):
            review = await _create_review_for_plan(db, plan, message)
            return (
                "ReviewTool 已执行："
                f"完成率 {round(review.completion_rate * 100)}%。"
                f"复盘：{review.summary}"
            )

        if _wants_knowledge_search(message):
            hits = ChromaKnowledgeBase().query(goal.id, message, top_k=3)
            if not hits:
                return "KnowledgeSearchTool 已执行：没有检索到足够相关的知识片段。"
            lines = []
            for index, hit in enumerate(hits, start=1):
                metadata = hit.get("metadata") or {}
                source = metadata.get("source") or metadata.get("filename") or "知识片段"
                lines.append(f"{index}. {source}：{str(hit.get('content') or '')[:220]}")
            return "KnowledgeSearchTool 已执行：\n" + "\n".join(lines)
    except HTTPException as exc:
        return f"工具执行失败：{exc.detail}"
    except Exception as exc:
        return f"工具执行失败：{exc}"

    return None


def _wants_review(message: str) -> bool:
    return "复盘" in message and not _wants_adjustment(message)


def _wants_adjustment(message: str) -> bool:
    return "调整" in message and ("计划" in message or "明天" in message or "后续" in message)


def _wants_knowledge_search(message: str) -> bool:
    return any(token in message for token in ["查一下", "检索", "知识库", "资料里"])


def _wants_knowledge_insert(message: str) -> bool:
    return any(token in message for token in ["加入知识库", "写入知识库", "补充到知识库", "记到知识库"])


def _extract_snippet_content(message: str) -> str:
    """尽量从自然语言里抽出要写入知识库的正文。"""

    markers = ["加入知识库：", "写入知识库：", "补充到知识库：", "记到知识库："]
    for marker in markers:
        if marker in message:
            return message.split(marker, 1)[1].strip() or message
    return message


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


def _quiz_payload(quiz: models.TaskQuiz) -> dict:
    """把 TaskQuiz ORM 对象转换成前端需要的响应结构。"""

    source_mode = (
        quiz.source_mode if quiz.source_mode in {"rag", "llm_fallback"} else "llm_fallback"
    )
    return {
        "id": quiz.id,
        "task_id": quiz.task_id,
        "plan_id": quiz.plan_id,
        "goal_id": quiz.goal_id,
        "status": quiz.status,
        "source_mode": source_mode,
        "questions": quiz.questions_json or [],
        "answers": quiz.answers_json or [],
        "result": quiz.result_json,
        "created_at": quiz.created_at,
        "submitted_at": quiz.submitted_at,
    }


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


def _chat_context(payload: ChatStreamRequest, db: Session) -> str:
    """组装聊天助手可见的学习上下文。

    聊天不直接修改业务数据，只读取当前目标、选中计划、任务打卡状态，
    并用最后一条用户消息检索 Chroma。上下文长度做了控制，避免 prompt
    过长影响响应速度。
    """

    sections: list[str] = []
    goal = crud.get_goal(db, payload.goal_id) if payload.goal_id else None
    plan = crud.get_plan(db, payload.plan_id) if payload.plan_id else None
    last_user_message = _last_user_message(payload)

    if goal is not None:
        sections.append(
            "\n".join(
                [
                    "当前学习目标：",
                    f"- 标题：{goal.title}",
                    f"- 考试日期：{goal.exam_date}",
                    f"- 每日可用时间：{goal.daily_minutes} 分钟",
                    f"- 当前基础：{goal.current_level}",
                    f"- 重点章节：{', '.join(goal.key_topics)}",
                ]
            )
        )

    if plan is not None:
        tasks = crud.list_tasks(db, plan.id)
        task_lines = [
            f"- {item.title}（{item.status}，{item.estimated_minutes} 分钟）"
            for item in tasks[:8]
        ]
        sections.append(
            "\n".join(
                [
                    "当前选中的每日计划：",
                    f"- Day {plan.day_index}：{plan.topic}",
                    f"- 日期：{plan.plan_date}",
                    f"- 目标：{plan.objective}",
                    "当前任务：",
                    *(task_lines or ["- 暂无已生成任务"]),
                ]
            )
        )

    knowledge_hits = _chat_knowledge_hits(goal, plan, last_user_message)
    if knowledge_hits:
        hit_lines = []
        for index, hit in enumerate(knowledge_hits, start=1):
            metadata = hit.get("metadata") or {}
            summary = metadata.get("summary_zh") or ""
            source = metadata.get("source") or metadata.get("filename") or "课程资料"
            content = str(hit.get("content") or "")[:700]
            hit_lines.append(
                f"[资料 {index}] {source}\n中文摘要：{summary}\n片段：{content}"
            )
        sections.append("课程资料检索结果：\n" + "\n\n".join(hit_lines))

    return "\n\n".join(sections)


def _chat_system_prompt(context: str) -> str:
    """构造学习助手的系统提示词。"""

    return "\n".join(
        [
            "你是 StudyAgent 的 AI 学习助手，面向正在备考的大学生。",
            "请用中文回答，结构清晰，尽量给出可执行的学习建议。",
            "如果用户询问知识点，请先解释直觉，再给简短例子或记忆方法。",
            "请使用 Markdown 组织答案；代码、命令和配置用 fenced code block。",
            "数学公式请使用 LaTeX：行内公式用 \\(...\\)，独立公式用 \\[...\\]。",
            "如果提供了当前计划、任务或课程资料上下文，请优先结合这些内容。",
            "系统已注册轻量工具：KnowledgeSearchTool、KnowledgeIngestTool、ReviewTool、AdjustPlanTool；如果上下文里出现工具结果，请直接解释结果并给下一步建议。",
            "不要编造资料中没有的页码、公式编号或教材原句。",
            "当前上下文如下：",
            context or "暂无学习上下文。",
        ]
    )


def _fallback_chat_reply(payload: ChatStreamRequest, context: str) -> str:
    """没有 DeepSeek API Key 时的本地兜底回复。"""

    question = _last_user_message(payload) or "这个问题"
    if context:
        return (
            f"我先基于当前学习上下文回答：你问的是「{question}」。\n\n"
            "建议你把它拆成三步处理：\n"
            "1. 先回到当前 Day 的学习目标，确认这个问题属于哪个核心概念。\n"
            "2. 再结合任务卡片，把概念变成一道小练习或一次主动复述。\n"
            "3. 如果仍然卡住，把不理解的术语单独列出来，下一轮我可以继续帮你解释。\n\n"
            "当前本地未配置 DeepSeek API Key，所以这是规则兜底回复；配置 Key 后会切换为真正的流式模型回答。"
        )
    return (
        f"你问的是「{question}」。我建议先用一句话定义概念，再找一个例子验证理解。"
        "当前本地未配置 DeepSeek API Key，所以这是规则兜底回复。"
    )


def _last_user_message(payload: ChatStreamRequest) -> str:
    """取最近一条用户消息作为检索 query 和兜底回复依据。"""

    for item in reversed(payload.messages):
        if item.role == "user":
            return item.content.strip()
    return ""


def _chat_knowledge_hits(
    goal: models.LearningGoal | None,
    plan: models.StudyPlan | None,
    last_user_message: str,
) -> list[dict]:
    """为聊天助手检索少量课程资料片段。"""

    goal_id = goal.id if goal is not None else plan.goal_id if plan is not None else None
    if goal_id is None:
        return []

    query_parts = [last_user_message]
    if plan is not None:
        query_parts.extend([plan.topic, plan.objective])
    elif goal is not None:
        query_parts.extend([goal.title, *goal.key_topics])
    query = " ".join(item for item in query_parts if item).strip()
    if not query:
        return []

    try:
        return ChromaKnowledgeBase().query(goal_id, query, top_k=3)
    except Exception:
        return []


def _parse_key_topics(raw: str) -> list[str]:
    """解析 multipart 表单里的重点章节字段。

    前端用逗号分隔章节，后端统一清洗成字符串列表，便于复用 `GoalCreate`
    的校验和后续 Agent 输入格式。
    """

    return [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]


def _knowledge_context_for_goal(goal_id: int, payload: GoalCreate) -> list[dict]:
    """为 Planner Agent 检索目标级课程资料上下文。

    总计划还没有具体 day/topic，因此用学习目标标题和重点章节作为查询词。
    如果用户没有上传资料或 Chroma 暂时不可用，返回空列表，不影响普通计划生成。
    """

    query = " ".join([payload.title, *payload.key_topics]).strip()
    if not query:
        return []
    try:
        return ChromaKnowledgeBase().query(goal_id, query, top_k=6)
    except Exception:
        return []


def _knowledge_context_for_plan(plan: models.StudyPlan) -> list[dict]:
    """为 Task Agent 检索少量课程资料上下文。

    Chroma 异常不应该阻塞普通任务生成；如果还没有资料建库，
    Agent 会退回到第一版的生成方式。
    """

    try:
        scoped_hits = ChromaKnowledgeBase().query(
            plan.goal_id,
            plan.topic,
            top_k=3,
            day_index=plan.day_index,
        )
        if scoped_hits:
            return scoped_hits
        return ChromaKnowledgeBase().query(plan.goal_id, plan.topic, top_k=3)
    except Exception:
        return []
