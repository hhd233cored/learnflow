from __future__ import annotations

from datetime import date
from typing import Any, Awaitable, Callable, TypedDict

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - allows syntax checks before deps install
    END = "__end__"
    StateGraph = None

from app.agents.llm import DeepSeekClient
from app.agents.rules import (
    build_rule_based_adjustment,
    build_rule_based_plan,
    build_rule_based_review,
    build_rule_based_tasks,
)
from app.schemas import GoalCreate


class AgentState(TypedDict, total=False):
    """LangGraph 节点之间传递的共享状态对象。

    LangGraph 节点接收和返回的都是字典。使用 TypedDict 可以让 review 的人
    直观看到 Planner、Task、Review、Adjust 这些节点之间可能流转哪些字段。
    """

    goal: dict[str, Any]
    plan: dict[str, Any]
    daily_plan: dict[str, Any]
    tasks: list[dict[str, Any]]
    feedback: str
    review: dict[str, Any]
    tomorrow_plan: dict[str, Any]
    adjustment: dict[str, Any]


llm = DeepSeekClient()


async def _run_single_node(
    node_name: str,
    node: Callable[[AgentState], Awaitable[AgentState]],
    state: AgentState,
) -> AgentState:
    """通过 LangGraph 执行单个节点，同时保留直接调用兜底路径。

    第一版每个 API 动作只跑一个节点，但现在就把 LangGraph 放进执行路径，
    后续扩展成多节点工作流会更自然。
    """

    if StateGraph is None:
        return await node(state)

    graph = StateGraph(AgentState)
    graph.add_node(node_name, node)
    graph.set_entry_point(node_name)
    graph.add_edge(node_name, END)
    compiled = graph.compile()
    return await compiled.ainvoke(state)


async def generate_plan(
    goal: GoalCreate, knowledge_context: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """为学习目标生成完整每日计划，并做格式归一化。

    Planner Agent 可能会调用 DeepSeek，但每次运行都有确定性的本地规则兜底。
    返回值始终是可以直接写入 `study_plans` 的规范化计划字典列表。
    `knowledge_context` 来自用户上传资料的 Chroma 检索结果，用于让总计划
    尽量贴合教材/PPT 中真实出现的章节和概念。
    """

    goal_payload = goal.model_dump()
    if knowledge_context:
        goal_payload["knowledge_context"] = knowledge_context

    async def planner_node(state: AgentState) -> AgentState:
        """向 Planner Agent 请求 `daily_plans` JSON 的 LangGraph 节点。"""

        fallback = build_rule_based_plan(state["goal"])
        planned_days = len(fallback["daily_plans"])
        result = await llm.complete_json(
            system_prompt=(
                "你是 Planner Agent。请为大学生学习目标生成结构化计划，"
                "目标可能是考试倒计时，也可能是固定周期学完一门课。"
                "如果提供了课程资料上下文，请优先结合资料中的章节、概念和术语安排计划。"
                f"必须严格生成 {planned_days} 天计划，并返回 JSON，字段包含 daily_plans。"
            ),
            user_payload={
                "goal": state["goal"],
                "planned_days": planned_days,
                "knowledge_context": state["goal"].get("knowledge_context", []),
                "schema": _plan_schema_hint(),
            },
            fallback=fallback,
        )
        return {"plan": result}

    result = await _run_single_node("planner", planner_node, {"goal": goal_payload})
    fallback_items = build_rule_based_plan(goal_payload)["daily_plans"]
    return _normalize_daily_plans(result.get("plan", {}), fallback_items)


async def generate_tasks(goal: dict, daily_plan: dict) -> list[dict[str, Any]]:
    """为某一天计划生成可执行任务卡片。

    `daily_plan` 可能包含从 Chroma 检索到的 `knowledge_context`。
    Task Agent 可以利用这些上下文引用课程资料；如果没有检索数据，
    本地规则兜底仍然可以正常工作。
    """

    async def task_node(state: AgentState) -> AgentState:
        """把每日主题转换成任务 JSON 的 LangGraph 节点。"""

        fallback = build_rule_based_tasks(state["goal"], state["daily_plan"])
        result = await llm.complete_json(
            system_prompt=(
                "你是 Task Agent。请把当天学习主题拆成可执行任务，"
                "任务总时长不得超过用户每日可用时间，必须返回 JSON。"
            ),
            user_payload={
                "goal": state["goal"],
                "daily_plan": state["daily_plan"],
                "knowledge_context": state["daily_plan"].get("knowledge_context", []),
                "schema": _task_schema_hint(),
            },
            fallback=fallback,
        )
        return {"tasks": result.get("tasks", fallback["tasks"])}

    result = await _run_single_node(
        "task_generator", task_node, {"goal": goal, "daily_plan": daily_plan}
    )
    fallback_items = build_rule_based_tasks(goal, daily_plan)["tasks"]
    return _normalize_tasks(result.get("tasks", []), fallback_items, goal)


async def generate_review(
    goal: dict, daily_plan: dict, tasks: list[dict], feedback: str
) -> dict[str, Any]:
    """根据任务状态和用户反馈生成当天复盘。"""

    async def review_node(state: AgentState) -> AgentState:
        """向 Review Agent 请求总结和薄弱点的 LangGraph 节点。"""

        fallback = build_rule_based_review(
            state["daily_plan"], state["tasks"], state["feedback"]
        )
        result = await llm.complete_json(
            system_prompt=(
                "你是 Review Agent。请根据完成率、任务状态和用户反馈生成学习复盘，"
                "必须返回 JSON。"
            ),
            user_payload={
                "goal": state["goal"],
                "daily_plan": state["daily_plan"],
                "tasks": state["tasks"],
                "feedback": state["feedback"],
                "schema": _review_schema_hint(),
            },
            fallback=fallback,
        )
        return {"review": result}

    result = await _run_single_node(
        "reviewer",
        review_node,
        {"goal": goal, "daily_plan": daily_plan, "tasks": tasks, "feedback": feedback},
    )
    return _normalize_review(
        result.get("review", {}),
        build_rule_based_review(daily_plan, tasks, feedback),
    )


async def adjust_tomorrow_plan(
    goal: dict, tomorrow_plan: dict, review: dict
) -> dict[str, Any]:
    """根据最新复盘结果生成明日调整计划。"""

    async def adjust_node(state: AgentState) -> AgentState:
        """向 Adjust Agent 请求调整前后内容的 LangGraph 节点。"""

        fallback = build_rule_based_adjustment(state["tomorrow_plan"], state["review"])
        result = await llm.complete_json(
            system_prompt=(
                "你是 Adjust Agent。请根据复盘结果调整明日学习计划，"
                "必须返回 JSON。"
            ),
            user_payload={
                "goal": state["goal"],
                "tomorrow_plan": state["tomorrow_plan"],
                "review": state["review"],
                "schema": _adjust_schema_hint(),
            },
            fallback=fallback,
        )
        return {"adjustment": result}

    result = await _run_single_node(
        "adjuster",
        adjust_node,
        {"goal": goal, "tomorrow_plan": tomorrow_plan, "review": review},
    )
    return _normalize_adjustment(
        result.get("adjustment", {}),
        build_rule_based_adjustment(tomorrow_plan, review),
    )


def _normalize_daily_plans(raw: dict[str, Any], fallback: list[dict]) -> list[dict]:
    """校验并修复 Planner Agent 的输出。

    LLM 输出一律按不可信输入处理。这里会校验列表结构、最大长度、日期格式
    和必需字段。如果发现不安全或格式异常，就返回确定性的规则兜底计划。
    """

    items = raw.get("daily_plans")
    if not isinstance(items, list) or not items:
        return fallback

    expected_count = max(len(fallback), 1)
    normalized = []
    for index, item in enumerate(items[:expected_count], start=1):
        try:
            fallback_item = fallback[min(index - 1, len(fallback) - 1)]
            plan_date = item.get("plan_date") or fallback_item["plan_date"]
            if isinstance(plan_date, str):
                plan_date = date.fromisoformat(plan_date[:10])
            normalized.append(
                {
                    "day_index": int(item.get("day_index", index)),
                    "plan_date": plan_date,
                    "topic": str(item.get("topic") or fallback_item["topic"])[:200],
                    "objective": str(
                        item.get("objective") or fallback_item["objective"]
                    ),
                }
            )
        except Exception:
            return fallback
    # LLM 有时会少返回几天；为了保证“30 天计划”等固定周期目标不缩水，
    # 缺失部分直接补上规则兜底计划。
    if len(normalized) < len(fallback):
        normalized.extend(fallback[len(normalized):])
    return normalized or fallback


def _normalize_tasks(raw: list[dict], fallback: list[dict], goal: dict) -> list[dict]:
    """校验并修复 Task Agent 的输出。

    保证任务包含必需字段，限制任务数量，并确保总预计时长不会超过用户每日
    可用时间。
    """

    if not isinstance(raw, list) or not raw:
        return fallback

    daily_minutes = int(goal.get("daily_minutes", 120))
    normalized = []
    used_minutes = 0
    for item in raw[:6]:
        try:
            minutes = max(5, int(item.get("estimated_minutes", 20)))
            remaining = daily_minutes - used_minutes
            if remaining <= 0:
                break
            if minutes > remaining:
                minutes = remaining
            if minutes <= 0:
                break
            used_minutes += minutes
            normalized.append(
                {
                    "title": str(item.get("title") or "学习任务")[:200],
                    "description": str(item.get("description") or "完成指定学习内容。"),
                    "estimated_minutes": minutes,
                    "task_type": str(item.get("task_type") or "study")[:40],
                }
            )
        except Exception:
            return fallback
    return normalized or fallback


def _normalize_review(raw: dict[str, Any], fallback: dict) -> dict:
    """校验并修复 Review Agent 的输出。"""

    try:
        completion_rate = float(raw.get("completion_rate", fallback["completion_rate"]))
        return {
            "completion_rate": max(0.0, min(1.0, completion_rate)),
            "summary": str(raw.get("summary") or fallback["summary"]),
            "weak_points": _string_list(raw.get("weak_points"), fallback["weak_points"]),
            "suggestions": _string_list(raw.get("suggestions"), fallback["suggestions"]),
        }
    except Exception:
        return fallback


def _normalize_adjustment(raw: dict[str, Any], fallback: dict) -> dict:
    """校验并修复 Adjust Agent 的输出。"""

    return {
        "adjusted_topic": str(raw.get("adjusted_topic") or fallback["adjusted_topic"])[:200],
        "adjusted_objective": str(
            raw.get("adjusted_objective") or fallback["adjusted_objective"]
        ),
        "reason": str(raw.get("reason") or fallback["reason"]),
    }


def _string_list(value: Any, fallback: list[str]) -> list[str]:
    """返回一个短的非空字符串列表；格式不对时使用兜底列表。"""

    if not isinstance(value, list):
        return fallback
    cleaned = [str(item) for item in value if str(item).strip()]
    return cleaned[:6] or fallback


def _plan_schema_hint() -> dict:
    """发送给 Planner Agent 的 schema 示例，用于约束结构化 JSON 输出。"""

    return {
        "daily_plans": [
            {
                "day_index": 1,
                "plan_date": "YYYY-MM-DD",
                "topic": "进程与线程",
                "objective": "理解核心概念并完成基础练习",
            }
        ]
    }


def _task_schema_hint() -> dict:
    """发送给 Task Agent 的 schema 示例，用于约束结构化 JSON 输出。"""

    return {
        "tasks": [
            {
                "title": "任务标题",
                "description": "任务说明",
                "estimated_minutes": 25,
                "task_type": "knowledge|practice|review|recall",
            }
        ]
    }


def _review_schema_hint() -> dict:
    """发送给 Review Agent 的 schema 示例，用于约束结构化 JSON 输出。"""

    return {
        "completion_rate": 0.75,
        "summary": "今日复盘总结",
        "weak_points": ["PV 操作"],
        "suggestions": ["明天先补薄弱点再推进新内容"],
    }


def _adjust_schema_hint() -> dict:
    """发送给 Adjust Agent 的 schema 示例，用于约束结构化 JSON 输出。"""

    return {
        "adjusted_topic": "补强 PV 操作 + 内存管理",
        "adjusted_objective": "调整后的明日目标",
        "reason": "调整原因",
    }
