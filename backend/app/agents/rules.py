from __future__ import annotations

import re
from datetime import date, timedelta


DEFAULT_OS_TOPICS = [
    "进程与线程",
    "进程同步与互斥",
    "死锁",
    "内存管理",
    "虚拟内存",
    "文件系统",
    "I/O 与磁盘调度",
    "综合刷题与错题复盘",
]


def infer_day_count(goal: dict) -> int:
    """从目标模式、标题或考试日期推断计划天数。

    固定周期模式优先使用用户明确填写的 `duration_days`。考试模式保留
    原来的“考试日期 - 今天”逻辑；标题中的“10 天/30 天”作为兼容兜底。
    """

    duration_days = goal.get("duration_days")
    if goal.get("goal_type") == "duration" and duration_days:
        return min(max(int(duration_days), 3), 120)

    title = goal.get("title", "")
    match = re.search(r"(\d+)\s*天", title)
    if match:
        return min(max(int(match.group(1)), 3), 120)

    exam_date = goal.get("exam_date")
    if isinstance(exam_date, str):
        exam_date = date.fromisoformat(exam_date)
    if isinstance(exam_date, date):
        days_left = (exam_date - date.today()).days
        return min(max(days_left, 3), 120)
    return 10


def build_rule_based_plan(goal: dict) -> dict:
    """在 LLM 不可用时生成确定性的学习计划。

    这个兜底逻辑故意保持简单，但仍然符合产品形态：前期覆盖重点章节，
    后期切换到综合练习和考前复盘。即使没有 API Key，也能保证 Demo 稳定。
    """

    day_count = infer_day_count(goal)
    topics = goal.get("key_topics") or _topics_from_material_context(goal) or DEFAULT_OS_TOPICS
    topic_pool = [*topics, *DEFAULT_OS_TOPICS]
    material_note = _material_note(goal)
    start_date = date.today()
    daily_plans = []

    for index in range(day_count):
        if index == day_count - 1:
            topic = "综合复盘与学习总结"
            objective = "整合重点概念、错题和薄弱环节，完成一次综合检测或知识地图整理。"
        elif index >= max(day_count - 2, 1):
            topic = "综合练习与错题复盘"
            objective = f"用练习暴露知识漏洞，沉淀错题原因和解题模板。{material_note}"
        else:
            topic = topic_pool[index % len(topic_pool)]
            objective = f"围绕「{topic}」建立核心概念框架，并完成基础题巩固。{material_note}"

        daily_plans.append(
            {
                "day_index": index + 1,
                "plan_date": start_date + timedelta(days=index),
                "topic": topic,
                "objective": objective,
            }
        )

    return {
        "stages": [
            {"name": "基础梳理", "goal": "快速建立知识框架"},
            {"name": "重点突破", "goal": "围绕薄弱章节集中练习"},
            {"name": "刷题复盘", "goal": "通过错题反推复习重点"},
        ],
        "daily_plans": daily_plans,
    }


def _topics_from_material_context(goal: dict) -> list[str]:
    """从资料检索片段中提取少量可能的章节标题，作为规则兜底计划的主题。

    这不是语义理解，只是让未配置 LLM 的本地 Demo 也能体现“资料参与规划”。
    真正的章节理解仍然交给 Planner Agent 和大模型完成。
    """

    topics: list[str] = []
    for hit in goal.get("knowledge_context") or []:
        content = str(hit.get("content") or "")
        for line in content.splitlines():
            cleaned = line.strip(" #\t:-—")
            if 4 <= len(cleaned) <= 40 and cleaned not in topics:
                topics.append(cleaned)
            if len(topics) >= 5:
                return topics
    return topics


def _material_note(goal: dict) -> str:
    """生成一段简短说明，让兜底计划也明确它参考了上传资料。"""

    hits = goal.get("knowledge_context") or []
    if not hits:
        return ""
    filenames = []
    for hit in hits:
        metadata = hit.get("metadata") or {}
        filename = metadata.get("filename")
        if filename and filename not in filenames:
            filenames.append(filename)
    if not filenames:
        return " 结合上传资料中的相关章节。"
    return f" 结合上传资料「{'、'.join(filenames[:2])}」中的相关章节。"


def build_rule_based_tasks(goal: dict, plan: dict) -> dict:
    """为某一天计划生成确定性的每日任务。

    任务组合模拟一个合理的学习 session：知识输入、专项练习、错题复盘、
    主动回忆。每类任务的时长来自用户每日可用时间。
    """

    daily_minutes = int(goal.get("daily_minutes", 120))
    topic = plan.get("topic", "今日主题")
    reference_note = _reference_note(plan)
    knowledge_minutes = max(20, int(daily_minutes * 0.3))
    practice_minutes = max(25, int(daily_minutes * 0.38))
    review_minutes = max(15, int(daily_minutes * 0.18))
    recall_minutes = max(10, daily_minutes - knowledge_minutes - practice_minutes - review_minutes)

    tasks = [
        {
            "title": f"梳理「{topic}」核心概念",
            "description": f"阅读教材或课件，写下 3 个核心概念和 2 个易混点。{reference_note}",
            "estimated_minutes": knowledge_minutes,
            "task_type": "knowledge",
        },
        {
            "title": f"完成「{topic}」专项练习",
            "description": "完成 5-8 道相关题目，标记不确定题和错误原因。",
            "estimated_minutes": practice_minutes,
            "task_type": "practice",
        },
        {
            "title": "整理错题与薄弱点",
            "description": "把错题归因到概念不清、步骤遗漏或审题问题。",
            "estimated_minutes": review_minutes,
            "task_type": "review",
        },
        {
            "title": "三句话复述今日知识",
            "description": "不用看资料，用自己的话复述今日主题的核心逻辑。",
            "estimated_minutes": recall_minutes,
            "task_type": "recall",
        },
    ]
    return {"tasks": tasks}


def _reference_note(plan: dict) -> str:
    """当 Chroma 检索到课程资料时，生成一段简短的资料来源说明。"""

    hits = plan.get("knowledge_context") or []
    if not hits:
        return ""
    first = hits[0]
    metadata = first.get("metadata") or {}
    source = metadata.get("source") or metadata.get("filename")
    if not source:
        return ""
    return f" 参考资料：{source}。"


def calculate_completion_rate(tasks: list[dict]) -> float:
    """根据任务状态计算加权完成率。

    完成记 1.0，部分完成记 0.5，未完成或未开始记 0.0。
    """

    if not tasks:
        return 0.0
    score = 0.0
    for task in tasks:
        if task.get("status") == "done":
            score += 1.0
        elif task.get("status") == "partial":
            score += 0.5
    return round(score / len(tasks), 2)


def extract_weak_points(tasks: list[dict], feedback: str) -> list[str]:
    """从用户反馈和未完成任务中推断薄弱点。

    这是一个轻量启发式规则，用来给 Review Agent 的兜底输出提供足够信号，
    让后续计划调整能有依据。后续可以替换为分类器或更完整的学习画像模型。
    """

    weak_points: list[str] = []
    feedback_lower = feedback.lower()

    if "pv" in feedback_lower or "信号量" in feedback:
        weak_points.extend(["PV 操作", "信号量"])
    if "死锁" in feedback:
        weak_points.append("死锁判定")
    if "内存" in feedback:
        weak_points.append("内存管理")

    for task in tasks:
        if task.get("status") in {"partial", "missed"}:
            weak_points.append(task.get("title", "未完成任务"))

    deduped = []
    for item in weak_points:
        if item and item not in deduped:
            deduped.append(item)
    return deduped[:4] or ["知识点复述稳定性"]


def build_rule_based_review(plan: dict, tasks: list[dict], feedback: str) -> dict:
    """在 LLM 不可用时生成确定性的每日复盘。"""

    completion_rate = calculate_completion_rate(tasks)
    weak_points = extract_weak_points(tasks, feedback)
    topic = plan.get("topic", "今日主题")

    if completion_rate >= 0.85:
        summary = f"今天对「{topic}」推进顺利，可以进入下一主题，但仍建议保留少量错题复盘。"
        suggestions = ["明天保留 20 分钟回看错题", "新知识学习后立即做小题验证"]
    elif completion_rate >= 0.5:
        summary = f"今天完成度中等，「{topic}」已有基础，但薄弱点还需要专项补强。"
        suggestions = ["明天先补薄弱点再推进新内容", "把练习题按错误原因分类"]
    else:
        summary = f"今天执行压力偏大，「{topic}」建议降低新内容比例，先恢复节奏。"
        suggestions = ["明天减少新知识输入", "任务拆得更短，每 25 分钟完成一个小目标"]

    return {
        "completion_rate": completion_rate,
        "summary": summary,
        "weak_points": weak_points,
        "suggestions": suggestions,
    }


def build_rule_based_adjustment(
    tomorrow_plan: dict, review: dict
) -> dict:
    """根据复盘结果生成确定性的明日计划调整。"""

    weak_point = (review.get("weak_points") or ["今日薄弱点"])[0]
    original_topic = tomorrow_plan.get("topic", "明日计划")
    adjusted_topic = f"补强{weak_point} + {original_topic}"
    adjusted_objective = (
        f"先用 30-40 分钟回补「{weak_point}」，再推进「{original_topic}」的基础内容，"
        "避免薄弱点继续滚雪球。"
    )
    reason = (
        f"今日完成率为 {int(review.get('completion_rate', 0) * 100)}%，"
        f"主要薄弱点集中在「{weak_point}」，因此明日计划先补弱再推进。"
    )
    return {
        "adjusted_topic": adjusted_topic,
        "adjusted_objective": adjusted_objective,
        "reason": reason,
    }
