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
    """Run a node through LangGraph while keeping a direct fallback path.

    The first product version uses one node per API action. Keeping LangGraph in
    the execution path now makes it easy to expand into a multi-step graph later.
    """

    if StateGraph is None:
        return await node(state)

    graph = StateGraph(AgentState)
    graph.add_node(node_name, node)
    graph.set_entry_point(node_name)
    graph.add_edge(node_name, END)
    compiled = graph.compile()
    return await compiled.ainvoke(state)


async def generate_plan(goal: GoalCreate) -> list[dict[str, Any]]:
    goal_payload = goal.model_dump()

    async def planner_node(state: AgentState) -> AgentState:
        fallback = build_rule_based_plan(state["goal"])
        result = await llm.complete_json(
            system_prompt=(
                "你是 Planner Agent。请为大学生期末复习生成结构化计划，"
                "必须返回 JSON，字段包含 daily_plans。"
            ),
            user_payload={"goal": state["goal"], "schema": _plan_schema_hint()},
            fallback=fallback,
        )
        return {"plan": result}

    result = await _run_single_node("planner", planner_node, {"goal": goal_payload})
    fallback_items = build_rule_based_plan(goal_payload)["daily_plans"]
    return _normalize_daily_plans(result.get("plan", {}), fallback_items)


async def generate_tasks(goal: dict, daily_plan: dict) -> list[dict[str, Any]]:
    async def task_node(state: AgentState) -> AgentState:
        fallback = build_rule_based_tasks(state["goal"], state["daily_plan"])
        result = await llm.complete_json(
            system_prompt=(
                "你是 Task Agent。请把当天学习主题拆成可执行任务，"
                "任务总时长不得超过用户每日可用时间，必须返回 JSON。"
            ),
            user_payload={
                "goal": state["goal"],
                "daily_plan": state["daily_plan"],
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
    async def review_node(state: AgentState) -> AgentState:
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
    async def adjust_node(state: AgentState) -> AgentState:
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
    items = raw.get("daily_plans")
    if not isinstance(items, list) or not items:
        return fallback

    normalized = []
    for index, item in enumerate(items[:14], start=1):
        try:
            plan_date = item.get("plan_date") or fallback[min(index - 1, len(fallback) - 1)][
                "plan_date"
            ]
            if isinstance(plan_date, str):
                plan_date = date.fromisoformat(plan_date[:10])
            normalized.append(
                {
                    "day_index": int(item.get("day_index", index)),
                    "plan_date": plan_date,
                    "topic": str(item.get("topic") or fallback[index - 1]["topic"])[:200],
                    "objective": str(
                        item.get("objective") or fallback[index - 1]["objective"]
                    ),
                }
            )
        except Exception:
            return fallback
    return normalized or fallback


def _normalize_tasks(raw: list[dict], fallback: list[dict], goal: dict) -> list[dict]:
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
    return {
        "adjusted_topic": str(raw.get("adjusted_topic") or fallback["adjusted_topic"])[:200],
        "adjusted_objective": str(
            raw.get("adjusted_objective") or fallback["adjusted_objective"]
        ),
        "reason": str(raw.get("reason") or fallback["reason"]),
    }


def _string_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return fallback
    cleaned = [str(item) for item in value if str(item).strip()]
    return cleaned[:6] or fallback


def _plan_schema_hint() -> dict:
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
    return {
        "completion_rate": 0.75,
        "summary": "今日复盘总结",
        "weak_points": ["PV 操作"],
        "suggestions": ["明天先补薄弱点再推进新内容"],
    }


def _adjust_schema_hint() -> dict:
    return {
        "adjusted_topic": "补强 PV 操作 + 内存管理",
        "adjusted_objective": "调整后的明日目标",
        "reason": "调整原因",
    }
