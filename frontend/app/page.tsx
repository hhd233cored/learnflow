"use client";

import { useMemo, useState } from "react";
import {
  ArrowRight,
  CalendarDays,
  Check,
  ClipboardList,
  Loader2,
  RefreshCcw,
  Sparkles,
  Target,
  TimerReset
} from "lucide-react";
import { api, Adjustment, GoalDetail, Review, StudyTask } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";

const statusLabels: Record<string, string> = {
  pending: "未开始",
  partial: "部分完成",
  done: "已完成",
  missed: "未完成"
};

const statusTone: Record<string, "neutral" | "teal" | "amber" | "rose"> = {
  pending: "neutral",
  partial: "amber",
  done: "teal",
  missed: "rose"
};

const today = new Date();
const defaultExamDate = new Date(today);
defaultExamDate.setDate(today.getDate() + 10);

function formatDateInput(date: Date) {
  return date.toISOString().slice(0, 10);
}

export default function Home() {
  const [goal, setGoal] = useState<GoalDetail | null>(null);
  const [tasks, setTasks] = useState<StudyTask[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [adjustment, setAdjustment] = useState<Adjustment | null>(null);
  const [feedback, setFeedback] = useState("PV 操作题错得比较多，信号量含义有点混。");
  const [loadingStep, setLoadingStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({
    title: "10 天复习操作系统",
    examDate: formatDateInput(defaultExamDate),
    dailyMinutes: 120,
    currentLevel: "一般",
    keyTopics: "进程, 内存管理, 文件系统"
  });

  const todayPlan = goal?.plans?.[0] ?? null;
  const completionRate = useMemo(() => {
    if (tasks.length === 0) {
      return 0;
    }
    const score = tasks.reduce((total, task) => {
      if (task.status === "done") {
        return total + 1;
      }
      if (task.status === "partial") {
        return total + 0.5;
      }
      return total;
    }, 0);
    return Math.round((score / tasks.length) * 100);
  }, [tasks]);

  async function run<T>(step: string, action: () => Promise<T>): Promise<T | null> {
    setLoadingStep(step);
    setError(null);
    try {
      return await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败");
      return null;
    } finally {
      setLoadingStep(null);
    }
  }

  async function handleCreateGoal() {
    const keyTopics = form.keyTopics
      .split(/[,，]/)
      .map((item) => item.trim())
      .filter(Boolean);

    const created = await run("goal", () =>
      api.createGoal({
        title: form.title,
        exam_date: form.examDate,
        daily_minutes: Number(form.dailyMinutes),
        current_level: form.currentLevel,
        key_topics: keyTopics
      })
    );

    if (created) {
      setGoal(created);
      setTasks([]);
      setReview(null);
      setAdjustment(null);
    }
  }

  async function handleGenerateTasks() {
    if (!todayPlan) {
      return;
    }
    const generated = await run("tasks", () => api.generateTasks(todayPlan.id));
    if (generated) {
      setTasks(generated);
      setReview(null);
      setAdjustment(null);
    }
  }

  async function handleUpdateTask(taskId: number, status: string) {
    const updated = await run(`task-${taskId}`, () =>
      api.updateTaskStatus(taskId, status)
    );
    if (updated) {
      setTasks((current) =>
        current.map((task) => (task.id === taskId ? updated : task))
      );
    }
  }

  async function handleReview() {
    if (!todayPlan) {
      return;
    }
    const created = await run("review", () =>
      api.createReview(todayPlan.id, feedback)
    );
    if (created) {
      setReview(created);
    }
  }

  async function handleAdjust() {
    if (!goal || !todayPlan) {
      return;
    }
    const created = await run("adjust", () =>
      api.adjustTomorrow(goal.id, todayPlan.day_index)
    );
    if (created) {
      setAdjustment(created);
      const refreshed = await api.getGoal(goal.id);
      setGoal(refreshed);
    }
  }

  const isBusy = loadingStep !== null;

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-6 px-4 py-6 md:px-8">
      <header className="flex flex-col gap-4 border-b pb-5 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium text-primary">
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            <span>AI 学习执行官</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-normal md:text-3xl">
            从目标到复盘的学习执行工作台
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone="teal">LangGraph Agent</Badge>
          <Badge tone="amber">DeepSeek Ready</Badge>
          <Badge tone="rose">PostgreSQL Memory</Badge>
        </div>
      </header>

      {error ? (
        <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <section className="grid gap-6 lg:grid-cols-[380px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Target className="h-5 w-5 text-primary" aria-hidden="true" />
              创建学习目标
            </CardTitle>
            <CardDescription>
              第一版聚焦期末突击复习，目标会直接进入 Agent 工作流。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="title">学习目标</Label>
              <Input
                id="title"
                value={form.title}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    title: event.target.value
                  }))
                }
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="examDate">考试日期</Label>
                <Input
                  id="examDate"
                  type="date"
                  value={form.examDate}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      examDate: event.target.value
                    }))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="dailyMinutes">每日分钟</Label>
                <Input
                  id="dailyMinutes"
                  type="number"
                  min={30}
                  value={form.dailyMinutes}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      dailyMinutes: Number(event.target.value)
                    }))
                  }
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="currentLevel">当前基础</Label>
              <select
                id="currentLevel"
                className="h-10 w-full rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={form.currentLevel}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    currentLevel: event.target.value
                  }))
                }
              >
                <option>薄弱</option>
                <option>一般</option>
                <option>较好</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="keyTopics">重点章节</Label>
              <Input
                id="keyTopics"
                value={form.keyTopics}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    keyTopics: event.target.value
                  }))
                }
              />
            </div>
            <Button className="w-full" onClick={handleCreateGoal} disabled={isBusy}>
              {loadingStep === "goal" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Sparkles className="h-4 w-4" aria-hidden="true" />
              )}
              生成学习计划
            </Button>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CalendarDays className="h-5 w-5 text-primary" aria-hidden="true" />
                总计划时间线
              </CardTitle>
              <CardDescription>
                Agent 会根据考试日期、时间预算和重点章节拆出每日主题。
              </CardDescription>
            </CardHeader>
            <CardContent>
              {goal ? (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {goal.plans.map((plan) => (
                    <div
                      className="rounded-md border bg-background p-4"
                      key={plan.id}
                    >
                      <div className="mb-3 flex items-center justify-between gap-3">
                        <Badge tone={plan.adjusted ? "amber" : "neutral"}>
                          Day {plan.day_index}
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          {plan.plan_date}
                        </span>
                      </div>
                      <h3 className="text-sm font-semibold">{plan.topic}</h3>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        {plan.objective}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState text="创建目标后，这里会出现 7-10 天复习路线。" />
              )}
            </CardContent>
          </Card>

          <section className="grid gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <ClipboardList
                    className="h-5 w-5 text-primary"
                    aria-hidden="true"
                  />
                  今日任务
                </CardTitle>
                <CardDescription>
                  {todayPlan
                    ? `Day ${todayPlan.day_index}：${todayPlan.topic}`
                    : "先生成总计划，再拆解今日任务。"}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">完成进度</span>
                    <span className="font-medium">{completionRate}%</span>
                  </div>
                  <Progress value={completionRate} />
                </div>

                {tasks.length > 0 ? (
                  <div className="space-y-3">
                    {tasks.map((task) => (
                      <div className="rounded-md border bg-background p-4" key={task.id}>
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="text-sm font-semibold">{task.title}</h3>
                              <Badge tone={statusTone[task.status] ?? "neutral"}>
                                {statusLabels[task.status] ?? task.status}
                              </Badge>
                            </div>
                            <p className="mt-2 text-sm leading-6 text-muted-foreground">
                              {task.description}
                            </p>
                          </div>
                          <Badge tone="teal">{task.estimated_minutes} 分钟</Badge>
                        </div>
                        <div className="mt-4 flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleUpdateTask(task.id, "done")}
                            disabled={isBusy}
                            title="标记完成"
                          >
                            <Check className="h-3.5 w-3.5" aria-hidden="true" />
                            完成
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => handleUpdateTask(task.id, "partial")}
                            disabled={isBusy}
                          >
                            部分完成
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleUpdateTask(task.id, "missed")}
                            disabled={isBusy}
                          >
                            未完成
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState text="今日任务会被拆成知识输入、专项练习和复述总结。" />
                )}

                <Button
                  variant="outline"
                  className="w-full"
                  onClick={handleGenerateTasks}
                  disabled={!todayPlan || isBusy}
                >
                  {loadingStep === "tasks" ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <TimerReset className="h-4 w-4" aria-hidden="true" />
                  )}
                  生成今日任务
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <RefreshCcw className="h-5 w-5 text-primary" aria-hidden="true" />
                  复盘与调整
                </CardTitle>
                <CardDescription>
                  根据任务状态和主观反馈，生成复盘并调整明日计划。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="feedback">今日反馈</Label>
                  <Textarea
                    id="feedback"
                    value={feedback}
                    onChange={(event) => setFeedback(event.target.value)}
                  />
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <Button onClick={handleReview} disabled={!todayPlan || isBusy}>
                    {loadingStep === "review" ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Sparkles className="h-4 w-4" aria-hidden="true" />
                    )}
                    生成 AI 复盘
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={handleAdjust}
                    disabled={!review || isBusy}
                  >
                    调整明日计划
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>

                {review ? (
                  <div className="rounded-md border bg-background p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <h3 className="text-sm font-semibold">今日复盘</h3>
                      <Badge tone="teal">
                        完成率 {Math.round(review.completion_rate * 100)}%
                      </Badge>
                    </div>
                    <p className="text-sm leading-6 text-muted-foreground">
                      {review.summary}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {review.weak_points.map((item) => (
                        <Badge tone="rose" key={item}>
                          {item}
                        </Badge>
                      ))}
                    </div>
                    <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
                      {review.suggestions.map((item) => (
                        <li key={item}>· {item}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {adjustment ? (
                  <div className="rounded-md border bg-amber-50 p-4">
                    <h3 className="text-sm font-semibold text-amber-900">
                      明日计划调整
                    </h3>
                    <div className="mt-3 grid gap-3 text-sm md:grid-cols-2">
                      <div>
                        <p className="font-medium text-muted-foreground">调整前</p>
                        <p className="mt-1">{adjustment.original_topic}</p>
                      </div>
                      <div>
                        <p className="font-medium text-muted-foreground">调整后</p>
                        <p className="mt-1">{adjustment.adjusted_topic}</p>
                      </div>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-amber-900">
                      {adjustment.reason}
                    </p>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </section>
        </div>
      </section>
    </main>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex min-h-32 items-center justify-center rounded-md border border-dashed bg-background px-4 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}

