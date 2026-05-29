from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from datetime import datetime

from app import models
from app.schemas import GoalCreate


def create_goal_with_plan(
    db: Session, payload: GoalCreate, daily_plans: list[dict]
) -> models.LearningGoal:
    """创建学习目标，并保存 Agent 生成的每日计划。

    这个函数会在 Planner Agent 返回计划后调用。先写入父级 goal，
    让 SQLAlchemy 分配 `goal.id`，再用这个 id 为每一天创建
    对应的 `StudyPlan` 记录。
    """

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


def create_goal_only(db: Session, payload: GoalCreate, status: str = "planning") -> models.LearningGoal:
    """只创建学习目标，不立即生成每日计划。

    异步长计划生成会先保存目标，再把生成计划的耗时操作交给 Celery。
    目标的状态先标记为 `planning`，任务成功后再改回 `active`。
    """

    goal = models.LearningGoal(
        title=payload.title,
        exam_date=payload.exam_date,
        daily_minutes=payload.daily_minutes,
        current_level=payload.current_level,
        key_topics=payload.key_topics,
        status=status,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def replace_goal_plans(
    db: Session, goal: models.LearningGoal, daily_plans: list[dict]
) -> models.LearningGoal:
    """替换某个目标下的所有每日计划。

    异步计划任务完成后会调用这里写入 Planner Agent 的结果。覆盖式写入可以
    防止重复运行任务后产生两套 Day 1、Day 2。
    """

    db.query(models.StudyPlan).filter(models.StudyPlan.goal_id == goal.id).delete()
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
    goal.status = "active"
    db.commit()
    return get_goal(db, goal.id)


def get_goal(db: Session, goal_id: int) -> models.LearningGoal | None:
    """查询一个学习目标，并预加载它的每日计划。

    前端展示目标时会同时展示计划时间线，因此这里一次性加载 plans，
    避免数据库 session 关闭后再触发懒加载。
    """

    stmt = (
        select(models.LearningGoal)
        .where(models.LearningGoal.id == goal_id)
        .options(selectinload(models.LearningGoal.plans))
    )
    return db.scalars(stmt).first()


def list_goal_summaries(db: Session) -> list[dict]:
    """列出所有学习目标的轻量摘要。

    前端“我的学习计划”只需要摘要信息，不需要一次性返回所有每日计划和任务，
    这样刷新首页时会更轻。
    """

    stmt = (
        select(models.LearningGoal)
        .options(
            selectinload(models.LearningGoal.plans),
            selectinload(models.LearningGoal.materials),
        )
        .order_by(models.LearningGoal.updated_at.desc())
    )
    goals = list(db.scalars(stmt).all())
    return [
        {
            "id": goal.id,
            "title": goal.title,
            "exam_date": goal.exam_date,
            "daily_minutes": goal.daily_minutes,
            "current_level": goal.current_level,
            "key_topics": goal.key_topics,
            "status": goal.status,
            "plan_count": len(goal.plans),
            "material_count": len(goal.materials),
            "created_at": goal.created_at,
            "updated_at": goal.updated_at,
        }
        for goal in goals
    ]


def delete_goal(db: Session, goal_id: int) -> bool:
    """删除学习目标及其关系型数据库中的关联数据。"""

    goal = db.get(models.LearningGoal, goal_id)
    if goal is None:
        return False
    db.delete(goal)
    db.commit()
    return True


def get_plan(db: Session, plan_id: int) -> models.StudyPlan | None:
    """查询某一天的学习计划，并预加载 API 需要的关联数据。

    生成任务需要父级 goal，生成复盘需要已有 tasks，调整计划可能会读取
    reviews。使用 `selectinload` 可以提前加载这些关系，减少后续访问时
    的额外查询。
    """

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
    """列出某一天计划下的所有任务卡片。"""

    stmt = select(models.StudyTask).where(models.StudyTask.plan_id == plan_id)
    return list(db.scalars(stmt).all())


def get_task_with_context(db: Session, task_id: int) -> models.StudyTask | None:
    """读取任务，并预加载生成小测所需的计划、目标和已有小测。

    Quiz Agent 需要知道任务所属的 Day、学习目标和重点章节；预加载这些关系可以
    避免路由层在 session 关闭后触发懒加载。
    """

    stmt = (
        select(models.StudyTask)
        .where(models.StudyTask.id == task_id)
        .options(
            selectinload(models.StudyTask.plan).selectinload(models.StudyPlan.goal),
            selectinload(models.StudyTask.quizzes),
        )
    )
    return db.scalars(stmt).first()


def replace_tasks(db: Session, plan_id: int, tasks: list[dict]) -> list[models.StudyTask]:
    """替换某一天计划下的所有任务。

    重新生成任务时按覆盖处理，而不是追加。这样可以保证 Demo 结果稳定，
    也避免用户多次点击“生成今日任务”后出现重复任务卡片。
    """

    # 重新生成任务时先删除旧任务和对应小测，避免同一天不断累积重复卡片。
    # 这里使用 bulk delete，ORM 级联不会自动触发，因此要先清理 task_quizzes。
    task_ids = list(
        db.scalars(
            select(models.StudyTask.id).where(models.StudyTask.plan_id == plan_id)
        ).all()
    )
    if task_ids:
        db.query(models.TaskQuiz).filter(models.TaskQuiz.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
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
    """更新单个任务的打卡状态。

    如果任务不存在则返回 `None`，由路由层转换成 404 HTTP 响应。
    """

    task = db.get(models.StudyTask, task_id)
    if task is None:
        return None
    task.status = status
    db.commit()
    db.refresh(task)
    return task


def latest_quiz_for_task(db: Session, task_id: int) -> models.TaskQuiz | None:
    """查询某个任务最近一次生成的小测。"""

    stmt = (
        select(models.TaskQuiz)
        .where(models.TaskQuiz.task_id == task_id)
        .order_by(models.TaskQuiz.created_at.desc())
    )
    return db.scalars(stmt).first()


def create_task_quiz(
    db: Session,
    task: models.StudyTask,
    questions: list[dict],
    source_mode: str,
) -> models.TaskQuiz:
    """保存任务级小测。

    Demo 版按任务生成 3 道题，题目 JSON 直接写入 task_quizzes，便于前端快速展示。
    """

    quiz = models.TaskQuiz(
        task_id=task.id,
        plan_id=task.plan_id,
        goal_id=task.plan.goal_id,
        status="generated",
        source_mode=source_mode,
        questions_json=questions,
    )
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    return quiz


def get_quiz(db: Session, quiz_id: int) -> models.TaskQuiz | None:
    """根据 id 查询任务小测。"""

    return db.get(models.TaskQuiz, quiz_id)


def submit_task_quiz(
    db: Session,
    quiz: models.TaskQuiz,
    answers: list[dict],
    result: dict,
) -> models.TaskQuiz:
    """保存用户答案和批改结果。"""

    quiz.answers_json = answers
    quiz.result_json = result
    quiz.status = "submitted"
    quiz.submitted_at = datetime.utcnow()
    db.commit()
    db.refresh(quiz)
    return quiz


def create_review(
    db: Session,
    plan: models.StudyPlan,
    review: dict,
    feedback: str,
) -> models.StudyReview:
    """保存某一天的 Review Agent 复盘结果。

    `review` 字典已经在 workflow 层完成格式归一化，这里只负责把字段
    映射到数据库列。
    """

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
    """查询某一天计划的最新复盘记录。

    调整计划时使用最新复盘，因为用户可能在修改任务状态或反馈后重新生成复盘。
    """

    stmt = (
        select(models.StudyReview)
        .where(models.StudyReview.plan_id == plan_id)
        .order_by(models.StudyReview.created_at.desc())
    )
    return db.scalars(stmt).first()


def get_plan_by_day(
    db: Session, goal_id: int, day_index: int
) -> models.StudyPlan | None:
    """根据目标 id 和 day_index 查询某一天的计划。"""

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
    """应用 Adjust Agent 的输出，并记录计划调整审计信息。

    `PlanAdjustment` 保存调整前后的内容，方便 Demo 展示和后续追踪；
    同时直接更新 `StudyPlan`，让时间线显示调整后的计划。
    """

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


def create_course_material(
    db: Session,
    goal_id: int,
    filename: str,
    file_type: str,
    storage_path: str,
    chroma_collection: str,
) -> models.CourseMaterial:
    """为上传的课程资料创建元数据记录。

    文件本体存储在磁盘上。数据库记录负责追踪解析/建库状态、对应的
    Chroma collection，以及失败原因等信息。
    """

    material = models.CourseMaterial(
        goal_id=goal_id,
        filename=filename,
        file_type=file_type,
        storage_path=storage_path,
        parse_status="pending",
        chroma_collection=chroma_collection,
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    return material


def get_material(db: Session, material_id: int) -> models.CourseMaterial | None:
    """查询单个课程资料，并预加载它的 chunk 元数据。"""

    stmt = (
        select(models.CourseMaterial)
        .where(models.CourseMaterial.id == material_id)
        .options(selectinload(models.CourseMaterial.chunks))
    )
    return db.scalars(stmt).first()


def list_materials(db: Session, goal_id: int) -> list[models.CourseMaterial]:
    """列出某个学习目标下的课程资料，按创建时间倒序排列。"""

    stmt = (
        select(models.CourseMaterial)
        .where(models.CourseMaterial.goal_id == goal_id)
        .order_by(models.CourseMaterial.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def mark_material_processing(db: Session, material: models.CourseMaterial) -> None:
    """把资料状态标记为解析/建库中。"""

    material.parse_status = "processing"
    material.error_message = None
    db.commit()


def mark_material_failed(
    db: Session, material: models.CourseMaterial, error_message: str
) -> models.CourseMaterial:
    """记录资料解析或建库失败信息，供前端展示。"""

    material.parse_status = "failed"
    material.error_message = error_message[:2000]
    db.commit()
    db.refresh(material)
    return material


def replace_material_chunks(
    db: Session,
    material: models.CourseMaterial,
    chunks: list[str],
    chroma_document_ids: list[str],
) -> models.CourseMaterial:
    """Chroma 建库成功后，替换数据库中的 chunk 元数据。

    完整 chunk 文本和向量数据存放在 Chroma 中。关系型数据库只保存预览
    和 Chroma document id，用于展示建库状态，避免重复存储大量文本。
    """

    db.query(models.DocumentChunk).filter(
        models.DocumentChunk.material_id == material.id
    ).delete()

    for index, chunk in enumerate(chunks):
        db.add(
            models.DocumentChunk(
                material_id=material.id,
                chunk_index=index,
                content_preview=chunk[:500],
                chroma_collection=material.chroma_collection,
                chroma_document_id=chroma_document_ids[index],
            )
        )

    material.parse_status = "ready"
    material.error_message = None
    material.chunk_count = len(chunks)
    db.commit()
    db.refresh(material)
    return material


def create_job(
    db: Session,
    job_type: str,
    goal_id: int | None = None,
    result_json: dict | None = None,
) -> models.Job:
    """创建后台任务记录。

    API 在把任务投递给 Celery 前先写 Job，前端随后可以用 job_id 轮询状态。
    """

    job = models.Job(
        goal_id=goal_id,
        job_type=job_type,
        status="pending",
        progress=0,
        result_json=result_json,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: int) -> models.Job | None:
    """根据 id 查询后台任务记录。"""

    return db.get(models.Job, job_id)


def mark_job_running(db: Session, job: models.Job, progress: int = 5) -> models.Job:
    """把任务标记为运行中。"""

    job.status = "running"
    job.progress = progress
    job.error_message = None
    db.commit()
    db.refresh(job)
    return job


def update_job_progress(
    db: Session, job: models.Job, progress: int, result_json: dict | None = None
) -> models.Job:
    """更新任务进度和可选的中间结果。"""

    job.progress = max(0, min(100, progress))
    if result_json is not None:
        job.result_json = result_json
    db.commit()
    db.refresh(job)
    return job


def mark_job_success(
    db: Session, job: models.Job, result_json: dict | None = None
) -> models.Job:
    """把任务标记为成功完成。"""

    job.status = "success"
    job.progress = 100
    job.result_json = result_json or job.result_json
    job.error_message = None
    job.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job


def mark_job_failed(db: Session, job: models.Job, error_message: str) -> models.Job:
    """把任务标记为失败，并保存错误信息。"""

    job.status = "failed"
    job.error_message = error_message[:2000]
    job.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job
