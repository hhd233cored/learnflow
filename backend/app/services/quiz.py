from __future__ import annotations

import re
from typing import Any

from app import models
from app.agents.llm import DeepSeekClient
from app.services.knowledge_base import ChromaKnowledgeBase


RAG_DISTANCE_THRESHOLD = 1.4


async def generate_quiz_for_task(task: models.StudyTask) -> dict[str, Any]:
    """为单个任务生成 3 道 Demo 小测题。

    生成策略是“优先 RAG，质量不足时回退到通用 LLM 出题”。即使没有 DeepSeek
    API Key，也会使用本地规则生成可演示的题目，保证答题流程不断。
    """

    hits = _retrieve_quiz_context(task)
    source_mode = "rag" if _has_useful_hits(hits) else "llm_fallback"
    fallback = _rule_based_quiz(task, source_mode, hits)
    result = await DeepSeekClient().complete_json(
        system_prompt=(
            "你是 Quiz Agent。请为大学生每日学习任务生成 3 道中文知识点小测题。"
            "小测必须检测任务对应学科知识，而不是检测学习策略、任务执行方式或复盘方法。"
            "优先结合提供的课程资料；如果资料不足，请基于任务主题和通用课程知识出题，"
            "但不要假装引用资料。题目结构固定为：第 1 题概念辨析，第 2 题应用/计算/条件判断，"
            "第 3 题简答解释关键原理或步骤。禁止出现“最应该先确认什么”“更合理的处理方式”"
            "“请说明今天这个任务要掌握什么”等元学习题。题干、选项、参考答案和解析都可以使用 Markdown。"
            "所有数学公式必须使用 LaTeX 分隔符：行内公式用 \\(...\\)，独立公式用 \\[...\\]；"
            "矩阵请使用 \\begin{pmatrix}...\\end{pmatrix}。必须返回 JSON。"
        ),
        user_payload={
            "task": _task_payload(task),
            "daily_plan": _plan_payload(task.plan),
            "goal": _goal_payload(task.plan.goal),
            "source_mode": source_mode,
            "knowledge_context": hits if source_mode == "rag" else [],
            "schema": _quiz_schema_hint(),
        },
        fallback=fallback,
    )

    return {
        "source_mode": source_mode,
        "questions": _normalize_questions(result.get("questions"), fallback["questions"]),
    }


async def grade_quiz_answers(
    questions: list[dict[str, Any]], answers: list[dict[str, str]]
) -> dict[str, Any]:
    """批改任务小测答案，返回对错、单题分和总体建议。

    单选题会用确定性规则判断，简答题优先交给 LLM 做宽松批改；未配置 Key 时使用
    关键词和答案长度做大致判断。这里的分数只服务 Demo 反馈，不作为正式考试评分。
    """

    fallback = _rule_based_grade(questions, answers)
    result = await DeepSeekClient().complete_json(
        system_prompt=(
            "你是 Grading Agent。请宽松批改一组任务小测答案，返回 JSON。"
            "单选题按标准答案判断，简答题只需判断是否覆盖核心意思。"
            "分数是大致评估，不需要像正式考试一样严格。"
        ),
        user_payload={
            "questions": questions,
            "answers": answers,
            "schema": _grade_schema_hint(),
        },
        fallback=fallback,
    )
    return _normalize_grade_result(result, fallback, questions)


def _retrieve_quiz_context(task: models.StudyTask) -> list[dict[str, Any]]:
    """围绕任务主题检索 Chroma 资料片段。"""

    query = " ".join(
        [
            task.title,
            task.description,
            task.plan.topic,
            *list(task.plan.goal.key_topics or []),
        ]
    ).strip()
    if not query:
        return []

    try:
        return ChromaKnowledgeBase().query(task.plan.goal_id, query, top_k=4)
    except Exception:
        return []


def _has_useful_hits(hits: list[dict[str, Any]]) -> bool:
    """粗略判断 RAG 检索结果是否足够支撑出题。"""

    useful_count = 0
    for hit in hits:
        content = str(hit.get("content") or "").strip()
        distance = hit.get("distance")
        if len(content) < 80:
            continue
        if distance is None or float(distance) <= RAG_DISTANCE_THRESHOLD:
            useful_count += 1
    return useful_count >= 1


def _rule_based_quiz(
    task: models.StudyTask, source_mode: str, hits: list[dict[str, Any]]
) -> dict[str, Any]:
    """本地兜底出题，用于无 API Key 或模型失败时保持 Demo 可用。

    兜底题也必须检测学科知识点，不能退回“如何学习这个任务”的泛泛问题。
    对常见 demo 主题先给出小型题库；其余主题则生成概念/应用/简答三类通用题。
    """

    topic = task.title.replace("「", "").replace("」", "")
    plan_topic = task.plan.topic
    material_hint = _first_material_summary(hits)
    reference_suffix = f" 可结合资料要点：{material_hint}" if material_hint else ""
    normalized_topic = f"{topic} {plan_topic} {task.description}"

    if _contains_any(normalized_topic, ["Jacobi", "Gauss-Seidel", "高斯", "赛德尔"]):
        return _jacobi_gauss_seidel_quiz(source_mode)

    if _contains_any(normalized_topic, ["矩阵范数", "1-范数", "2-范数", "无穷范数", "谱范数"]):
        return _matrix_norm_quiz(source_mode)

    return {
        "source_mode": source_mode,
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "question": f"关于「{plan_topic}」，下列哪一项最符合该知识点的核心定义或判定条件？",
                "options": [
                    "A. 需要同时说明定义、适用条件和关键结论",
                    "B. 只要记住章节名称即可",
                    "C. 只看例题答案，不需要理解条件",
                    "D. 任意情况下都可以直接套同一个公式",
                ],
                "correct_answer": "A. 需要同时说明定义、适用条件和关键结论",
                "explanation": "知识点检测要覆盖概念边界、适用条件和结论，避免只记标题。",
            },
            {
                "id": "q2",
                "type": "single_choice",
                "question": f"在解决「{plan_topic}」相关题目时，哪类信息通常最能决定解法是否成立？",
                "options": [
                    "A. 题目给出的前提条件和目标结论",
                    "B. 题目所在页面的位置",
                    "C. 选项文字的长短",
                    "D. 是否刚好见过完全相同的题",
                ],
                "correct_answer": "A. 题目给出的前提条件和目标结论",
                "explanation": "应用题首先要识别条件是否满足，再决定能否使用某个公式、定理或算法。",
            },
            {
                "id": "q3",
                "type": "short_answer",
                "question": f"请解释「{plan_topic}」中的一个核心概念、适用条件和常见易错点。",
                "reference_answer": (
                    f"应围绕「{plan_topic}」给出概念定义，说明何时可以使用，"
                    f"并指出一个常见混淆点或错误步骤。{reference_suffix}"
                ),
                "explanation": "简答题检查对概念、条件和易错点的理解，而不是学习流程。",
            },
        ],
    }


def _normalize_questions(raw: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """校验 LLM 出题结果，异常时回退到本地题目。"""

    if not isinstance(raw, list) or not raw:
        return fallback

    normalized: list[dict[str, Any]] = []
    fallback_by_index = fallback
    for index, item in enumerate(raw[:3]):
        if not isinstance(item, dict):
            return fallback
        fallback_item = fallback_by_index[min(index, len(fallback_by_index) - 1)]
        question_type = str(item.get("type") or fallback_item["type"])
        if question_type not in {"single_choice", "short_answer"}:
            question_type = fallback_item["type"]

        question = str(item.get("question") or fallback_item["question"]).strip()
        if len(question) < 4 or _is_meta_learning_question(question):
            return fallback

        if question_type == "single_choice":
            fallback_options = fallback_item.get("options") or []
            options = _normalize_options(item.get("options"), fallback_options)
            correct_answer = _normalize_choice_answer(
                item.get("correct_answer"), options, fallback_item["correct_answer"]
            )
            normalized.append(
                {
                    "id": str(item.get("id") or f"q{index + 1}"),
                    "type": "single_choice",
                    "question": question[:500],
                    "options": options,
                    "correct_answer": correct_answer,
                    "explanation": str(
                        item.get("explanation") or fallback_item.get("explanation") or ""
                    )[:1000],
                }
            )
        else:
            normalized.append(
                {
                    "id": str(item.get("id") or f"q{index + 1}"),
                    "type": "short_answer",
                    "question": question[:500],
                    "options": [],
                    "reference_answer": str(
                        item.get("reference_answer")
                        or item.get("correct_answer")
                        or fallback_item.get("reference_answer")
                        or ""
                    )[:1200],
                    "explanation": str(
                        item.get("explanation") or fallback_item.get("explanation") or ""
                    )[:1000],
                }
            )

    return normalized if len(normalized) == 3 else fallback


def _jacobi_gauss_seidel_quiz(source_mode: str) -> dict[str, Any]:
    """Jacobi 与 Gauss-Seidel 迭代法的知识点兜底题。"""

    return {
        "source_mode": source_mode,
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "question": "关于 Jacobi 迭代法与 Gauss-Seidel 迭代法，下列说法正确的是哪一项？",
                "options": [
                    "A. Jacobi 使用上一轮的所有分量，Gauss-Seidel 会立即使用本轮已更新分量",
                    "B. 两者每一步使用的数据完全相同",
                    "C. Gauss-Seidel 必须先求出矩阵逆矩阵",
                    "D. Jacobi 只适用于非线性方程组",
                ],
                "correct_answer": "A. Jacobi 使用上一轮的所有分量，Gauss-Seidel 会立即使用本轮已更新分量",
                "explanation": "两种方法的关键差异在于新分量是否被立即用于后续分量更新。",
            },
            {
                "id": "q2",
                "type": "single_choice",
                "question": "若线性方程组系数矩阵严格对角占优，通常可以推出什么结论？",
                "options": [
                    "A. Jacobi 和 Gauss-Seidel 迭代通常收敛",
                    "B. 方程组一定没有解",
                    "C. 初值必须等于精确解",
                    "D. 每次迭代都不需要计算残差",
                ],
                "correct_answer": "A. Jacobi 和 Gauss-Seidel 迭代通常收敛",
                "explanation": "严格对角占优是判断这两类迭代法收敛的常见充分条件。",
            },
            {
                "id": "q3",
                "type": "short_answer",
                "question": "请简要说明 Jacobi 与 Gauss-Seidel 迭代格式在更新变量时的核心区别。",
                "reference_answer": (
                    "Jacobi 计算第 \\(k+1\\) 次迭代的各分量时统一使用第 \\(k\\) 次迭代的旧值；"
                    "Gauss-Seidel 在计算后面的分量时，会使用本轮已经得到的新值。"
                ),
                "explanation": "这个区别会影响算法实现、收敛速度和并行化方式。",
            },
        ],
    }


def _matrix_norm_quiz(source_mode: str) -> dict[str, Any]:
    """矩阵范数主题的知识点兜底题。"""

    return {
        "source_mode": source_mode,
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "question": "矩阵 \\(A\\) 的 \\(1\\)-范数通常定义为哪一项？",
                "options": [
                    "A. 各列元素绝对值和的最大值",
                    "B. 各行元素绝对值和的最大值",
                    "C. 所有元素的普通代数和",
                    "D. 主对角线元素之和",
                ],
                "correct_answer": "A. 各列元素绝对值和的最大值",
                "explanation": "\\(\\|A\\|_1\\) 是最大列和范数。",
            },
            {
                "id": "q2",
                "type": "single_choice",
                "question": "矩阵 \\(A\\) 的无穷范数 \\(\\|A\\|_\\infty\\) 通常定义为哪一项？",
                "options": [
                    "A. 各行元素绝对值和的最大值",
                    "B. 各列元素绝对值和的最大值",
                    "C. 最大特征值本身",
                    "D. 最小奇异值",
                ],
                "correct_answer": "A. 各行元素绝对值和的最大值",
                "explanation": "\\(\\|A\\|_\\infty\\) 是最大行和范数。",
            },
            {
                "id": "q3",
                "type": "short_answer",
                "question": "请说明矩阵 \\(2\\)-范数与 \\(A^T A\\) 的特征值之间的关系。",
                "reference_answer": (
                    "矩阵 \\(2\\)-范数等于最大奇异值，也可写为 "
                    "\\(\\|A\\|_2 = \\sqrt{\\lambda_{\\max}(A^T A)}\\)。"
                ),
                "explanation": "该关系把谱范数计算转化为对 \\(A^T A\\) 最大特征值的计算。",
            },
        ],
    }


def _normalize_options(raw: Any, fallback: list[str]) -> list[str]:
    """把选项规范成 4 个短字符串。"""

    if not isinstance(raw, list):
        return fallback
    options = [str(item).strip()[:300] for item in raw if str(item).strip()]
    return options[:4] if len(options) >= 2 else fallback


def _contains_any(text: str, keywords: list[str]) -> bool:
    """判断文本是否包含任一关键词，忽略英文大小写。"""

    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _is_meta_learning_question(question: str) -> bool:
    """识别“学习策略题/任务确认题”，这类题不应出现在知识点小测中。"""

    patterns = [
        "最应该先确认什么",
        "更合理的处理方式",
        "今天这个任务",
        "要掌握的核心内容",
        "只记录自己已经会",
        "跳过基础概念",
        "只看答案",
        "增加学习时长",
        "错题归因",
    ]
    return any(pattern in question for pattern in patterns)


def _normalize_choice_answer(raw: Any, options: list[str], fallback: str) -> str:
    """确保单选题标准答案能和某个选项精确匹配。"""

    value = str(raw or "").strip()
    if value in options:
        return value
    letter = value[:1].upper()
    if letter in {"A", "B", "C", "D"}:
        index = ord(letter) - ord("A")
        if index < len(options):
            return options[index]
    return fallback if fallback in options else options[0]


def _rule_based_grade(
    questions: list[dict[str, Any]], answers: list[dict[str, str]]
) -> dict[str, Any]:
    """本地兜底批改。"""

    answer_map = {item.get("question_id"): str(item.get("answer") or "") for item in answers}
    items = []
    for question in questions:
        question_id = str(question.get("id"))
        answer = answer_map.get(question_id, "").strip()
        if question.get("type") == "single_choice":
            correct_answer = str(question.get("correct_answer") or "")
            is_correct = _clean_answer(answer) == _clean_answer(correct_answer)
            items.append(
                {
                    "question_id": question_id,
                    "is_correct": is_correct,
                    "score": 100 if is_correct else 0,
                    "feedback": "回答正确。" if is_correct else "这一题需要回看标准选项对应的概念。",
                    "correct_answer": correct_answer,
                }
            )
        else:
            score = _short_answer_score(
                answer,
                str(question.get("reference_answer") or ""),
                str(question.get("question") or ""),
            )
            items.append(
                {
                    "question_id": question_id,
                    "is_correct": score >= 60,
                    "score": score,
                    "feedback": _short_answer_feedback(score),
                    "correct_answer": str(question.get("reference_answer") or ""),
                }
            )

    overall = _average_score(items)
    return {
        "score": overall,
        "items": items,
        "summary": _summary_for_score(overall),
    }


def _normalize_grade_result(
    raw: dict[str, Any], fallback: dict[str, Any], questions: list[dict[str, Any]]
) -> dict[str, Any]:
    """校验 LLM 批改结果。"""

    try:
        raw_items = raw.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            return fallback

        question_map = {str(item.get("id")): item for item in questions}
        items = []
        for item in raw_items:
            question_id = str(item.get("question_id") or "")
            if question_id not in question_map:
                continue
            score = _clamp_score(item.get("score", 0))
            question = question_map[question_id]
            items.append(
                {
                    "question_id": question_id,
                    "is_correct": bool(item.get("is_correct", score >= 60)),
                    "score": score,
                    "feedback": str(item.get("feedback") or "已完成批改。")[:1000],
                    "correct_answer": str(
                        item.get("correct_answer")
                        or question.get("correct_answer")
                        or question.get("reference_answer")
                        or ""
                    ),
                }
            )

        if not items:
            return fallback

        return {
            "score": _clamp_score(raw.get("score", _average_score(items))),
            "items": items,
            "summary": str(raw.get("summary") or _summary_for_score(_average_score(items)))[
                :1200
            ],
        }
    except Exception:
        return fallback


def _short_answer_score(answer: str, reference: str, question: str) -> int:
    """用关键词和长度给简答题一个粗略分数。"""

    if not answer.strip():
        return 0
    keywords = _keywords(reference) or _keywords(question)
    if keywords and any(keyword in answer for keyword in keywords):
        return 80 if len(answer) >= 12 else 65
    if len(answer) >= 28:
        return 60
    if len(answer) >= 10:
        return 40
    return 20


def _keywords(text: str) -> list[str]:
    """从中文文本中抽取少量可用于兜底批改的关键词。"""

    candidates = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", text)
    skipped = {"应围绕", "说明", "核心", "概念", "关键", "步骤", "典型", "应用"}
    result = []
    for item in candidates:
        if item in skipped or item in result:
            continue
        result.append(item)
        if len(result) >= 6:
            break
    return result


def _short_answer_feedback(score: int) -> str:
    """根据兜底分数生成简短反馈。"""

    if score >= 80:
        return "回答覆盖了主要意思，可以继续用题目巩固。"
    if score >= 60:
        return "回答基本相关，但还可以补充关键步骤或具体例子。"
    if score > 0:
        return "回答还比较泛，需要回到任务主题补充核心概念。"
    return "暂未作答。"


def _average_score(items: list[dict[str, Any]]) -> int:
    """计算平均分。"""

    if not items:
        return 0
    return round(sum(_clamp_score(item.get("score", 0)) for item in items) / len(items))


def _summary_for_score(score: int) -> str:
    """根据总分生成 Demo 级总结。"""

    if score >= 80:
        return "本次小测整体掌握较好，可以进入后续任务。"
    if score >= 60:
        return "本次小测基本达标，建议针对错误题回看相关知识点。"
    return "本次小测暴露出薄弱点，建议先复习任务对应概念，再继续推进。"


def _clamp_score(value: Any) -> int:
    """把任意分数压到 0-100。"""

    try:
        return max(0, min(100, int(round(float(value)))))
    except Exception:
        return 0


def _clean_answer(value: str) -> str:
    """规范化单选答案，减少空格和大小写造成的误判。"""

    return re.sub(r"\s+", "", value).lower()


def _first_material_summary(hits: list[dict[str, Any]]) -> str:
    """取一个资料摘要或片段，用于兜底简答参考答案。"""

    for hit in hits:
        metadata = hit.get("metadata") or {}
        summary = str(metadata.get("summary_zh") or "").strip()
        if summary:
            return summary[:180]
        content = str(hit.get("content") or "").strip()
        if content:
            return content[:180]
    return ""


def _goal_payload(goal: models.LearningGoal) -> dict[str, Any]:
    """把学习目标转成 LLM 输入。"""

    return {
        "id": goal.id,
        "title": goal.title,
        "goal_type": getattr(goal, "goal_type", "exam"),
        "exam_date": goal.exam_date,
        "duration_days": goal.duration_days,
        "daily_minutes": goal.daily_minutes,
        "current_level": goal.current_level,
        "key_topics": goal.key_topics,
    }


def _plan_payload(plan: models.StudyPlan) -> dict[str, Any]:
    """把每日计划转成 LLM 输入。"""

    return {
        "id": plan.id,
        "day_index": plan.day_index,
        "plan_date": plan.plan_date,
        "topic": plan.topic,
        "objective": plan.objective,
    }


def _task_payload(task: models.StudyTask) -> dict[str, Any]:
    """把任务转成 LLM 输入。"""

    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "estimated_minutes": task.estimated_minutes,
        "task_type": task.task_type,
        "status": task.status,
    }


def _quiz_schema_hint() -> dict[str, Any]:
    """Quiz Agent 的 JSON 输出示例。"""

    return {
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "question": "对于矩阵 \\(A\\)，其 \\(\\|A\\|_1\\) 等于多少？",
                "options": ["A. \\(5\\)", "B. \\(6\\)", "C. \\(4\\)", "D. \\(7\\)"],
                "correct_answer": "B. \\(6\\)",
                "explanation": "解析中也使用 Markdown 和 LaTeX。",
            },
            {
                "id": "q3",
                "type": "short_answer",
                "question": "请说明 \\(\\|A\\|_2 = \\sqrt{\\lambda_{\\max}(A^T A)}\\) 的含义。",
                "reference_answer": "参考答案可以包含公式，如 \\(A^T A\\)。",
                "explanation": "解析可以包含列表、代码或公式。",
            },
        ]
    }


def _grade_schema_hint() -> dict[str, Any]:
    """Grading Agent 的 JSON 输出示例。"""

    return {
        "score": 80,
        "items": [
            {
                "question_id": "q1",
                "is_correct": True,
                "score": 100,
                "feedback": "回答正确。",
                "correct_answer": "A. 选项",
            }
        ],
        "summary": "总体反馈",
    }
