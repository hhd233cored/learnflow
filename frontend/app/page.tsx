"use client";

import { useMemo, useState } from "react";
import {
  ArrowRight,
  CalendarDays,
  Check,
  Clock3,
  FileText,
  Loader2,
  RefreshCcw,
  Search,
  Sparkles,
  Target
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  Adjustment,
  CourseMaterial,
  GoalDetail,
  Job,
  KnowledgeSearchHit,
  Review,
  StudyPlan,
  StudyTask
} from "@/lib/api";
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
import { cn } from "@/lib/utils";

const POLL_INTERVAL_MS = 1000;
const MAX_PLAN_POLL_COUNT = 120;
const USE_ASYNC_JOBS = process.env.NEXT_PUBLIC_USE_ASYNC_JOBS === "true";

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

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function sortPlans(plans: StudyPlan[]) {
  return [...plans].sort((left, right) => left.day_index - right.day_index);
}

function getGoalIdFromJob(job: Job) {
  const rawGoalId = job.result_json?.goal_id ?? job.goal_id;
  if (typeof rawGoalId === "number") {
    return rawGoalId;
  }
  if (typeof rawGoalId === "string") {
    return Number(rawGoalId);
  }
  return null;
}

function getPlanJobLabel(job: Job | null) {
  if (!job) {
    return "等待开始";
  }
  if (job.status === "failed") {
    return "生成失败";
  }
  if (job.status === "success") {
    return "学习计划已生成";
  }
  if (job.status === "pending") {
    return "等待进入任务队列";
  }

  const stage = job.result_json?.stage;
  if (stage === "planning") {
    return "正在拆解阶段计划与每日安排";
  }
  return "正在生成学习计划";
}

function createLocalPlanJob(progress = 8): Job {
  return {
    id: 0,
    job_type: "local_generate_goal_plan",
    status: "running",
    progress,
    result_json: { stage: "planning" }
  };
}

export default function Home() {
  const [goal, setGoal] = useState<GoalDetail | null>(null);
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null);
  const [taskCache, setTaskCache] = useState<Record<number, StudyTask[]>>({});
  const [review, setReview] = useState<Review | null>(null);
  const [adjustment, setAdjustment] = useState<Adjustment | null>(null);
  const [materials, setMaterials] = useState<CourseMaterial[]>([]);
  const [knowledgeHits, setKnowledgeHits] = useState<KnowledgeSearchHit[]>([]);
  const [knowledgeQuery, setKnowledgeQuery] = useState("PV 操作 信号量");
  const [feedback, setFeedback] = useState("PV 操作题错得比较多，信号量含义有点混。");
  const [planJob, setPlanJob] = useState<Job | null>(null);
  const [loadingStep, setLoadingStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({
    title: "10 天复习操作系统",
    examDate: formatDateInput(defaultExamDate),
    dailyMinutes: 120,
    currentLevel: "一般",
    keyTopics: "进程, 内存管理, 文件系统"
  });

  const plans = useMemo(() => sortPlans(goal?.plans ?? []), [goal]);
  const selectedPlan = useMemo(() => {
    if (plans.length === 0) {
      return null;
    }
    return plans.find((plan) => plan.id === selectedPlanId) ?? plans[0];
  }, [plans, selectedPlanId]);

  const selectedTasks = selectedPlan ? taskCache[selectedPlan.id] ?? [] : [];
  const selectedTaskLoading = selectedPlan
    ? loadingStep === `tasks-${selectedPlan.id}`
    : false;

  const completionRate = useMemo(() => {
    if (selectedTasks.length === 0) {
      return 0;
    }
    const score = selectedTasks.reduce((total, task) => {
      if (task.status === "done") {
        return total + 1;
      }
      if (task.status === "partial") {
        return total + 0.5;
      }
      return total;
    }, 0);
    return Math.round((score / selectedTasks.length) * 100);
  }, [selectedTasks]);

  const planProgress = planJob?.progress ?? 0;
  const isPlanGenerating =
    planJob?.status === "pending" || planJob?.status === "running";
  const isBusy = loadingStep !== null || isPlanGenerating;

  async function run<T>(
    step: string,
    action: () => Promise<T>
  ): Promise<T | null> {
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

  async function pollPlanJob(jobId: number, initialJob: Job) {
    let currentJob = initialJob;

    // 前端通过轮询 jobs 表获得粗粒度进度；真正的耗时工作由 Celery worker 执行。
    for (let count = 0; count < MAX_PLAN_POLL_COUNT; count += 1) {
      setPlanJob(currentJob);

      if (currentJob.status === "success") {
        return currentJob;
      }
      if (currentJob.status === "failed") {
        throw new Error(currentJob.error_message ?? "计划生成失败");
      }

      await sleep(POLL_INTERVAL_MS);
      currentJob = await api.getJob(jobId);
    }

    throw new Error("计划生成时间较长，请确认 Redis 和 Celery worker 正在运行。");
  }

  async function ensureTasksForPlan(plan: StudyPlan) {
    const cachedTasks = taskCache[plan.id];
    if (cachedTasks && cachedTasks.length > 0) {
      return cachedTasks;
    }

    setLoadingStep(`tasks-${plan.id}`);
    setError(null);
    try {
      // 先读取已有任务，只有后端确实没有任务时才调用 Agent 按需生成。
      const existingTasks = await api.getTasks(plan.id);
      if (existingTasks.length > 0) {
        setTaskCache((current) => ({ ...current, [plan.id]: existingTasks }));
        return existingTasks;
      }

      const generatedTasks = await api.generateTasks(plan.id);
      setTaskCache((current) => ({ ...current, [plan.id]: generatedTasks }));
      return generatedTasks;
    } catch (err) {
      setError(err instanceof Error ? err.message : "任务加载失败");
      return [];
    } finally {
      setLoadingStep((current) =>
        current === `tasks-${plan.id}` ? null : current
      );
    }
  }

  async function selectPlan(plan: StudyPlan) {
    setSelectedPlanId(plan.id);
    setReview(null);
    setAdjustment(null);
    await ensureTasksForPlan(plan);
  }

  async function handleCreateGoal() {
    const keyTopics = form.keyTopics
      .split(/[,，]/)
      .map((item) => item.trim())
      .filter(Boolean);

    setGoal(null);
    setSelectedPlanId(null);
    setTaskCache({});
    setReview(null);
    setAdjustment(null);
    setMaterials([]);
    setKnowledgeHits([]);
    setPlanJob(null);
    setError(null);
    setLoadingStep("goal");

    const payload = {
      title: form.title,
      exam_date: form.examDate,
      daily_minutes: Number(form.dailyMinutes),
      current_level: form.currentLevel,
      key_topics: keyTopics
    };

    try {
      let createdGoal: GoalDetail;

      if (USE_ASYNC_JOBS) {
        const job = await api.createGoalAsync(payload);
        setPlanJob(job);

        const completedJob = await pollPlanJob(job.id, job);
        const goalId = getGoalIdFromJob(completedJob);
        if (!goalId) {
          throw new Error("计划已生成，但任务结果里没有返回 goal_id。");
        }

        createdGoal = await api.getGoal(goalId);
      } else {
        // 本地测试默认走同步接口，避免依赖 Redis/Celery；进度条由前端模拟。
        setPlanJob(createLocalPlanJob());
        const timer = window.setInterval(() => {
          setPlanJob((current) => {
            if (!current || current.status !== "running") {
              return current;
            }
            return {
              ...current,
              progress: Math.min(current.progress + 12, 92)
            };
          });
        }, 700);

        try {
          createdGoal = await api.createGoal(payload);
        } finally {
          window.clearInterval(timer);
        }

        setPlanJob({
          ...createLocalPlanJob(100),
          status: "success",
          result_json: { stage: "done", goal_id: createdGoal.id }
        });
      }

      setGoal(createdGoal);

      const firstPlan = sortPlans(createdGoal.plans)[0];
      if (firstPlan) {
        await selectPlan(firstPlan);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "计划生成失败");
    } finally {
      setLoadingStep(null);
    }
  }

  async function handleUploadMaterial(event: React.ChangeEvent<HTMLInputElement>) {
    if (!goal || !event.target.files?.[0]) {
      return;
    }
    const file = event.target.files[0];
    const uploaded = await run("material", () => api.uploadMaterial(goal.id, file));
    event.target.value = "";
    if (uploaded) {
      const nextMaterials = await api.listMaterials(goal.id);
      setMaterials(nextMaterials);
    }
  }

  async function handleSearchKnowledge() {
    if (!goal || !knowledgeQuery.trim()) {
      return;
    }
    const result = await run("knowledge", () =>
      api.searchKnowledge(goal.id, knowledgeQuery.trim(), 5)
    );
    if (result) {
      setKnowledgeHits(result.hits);
    }
  }

  async function handleUpdateTask(taskId: number, status: string) {
    if (!selectedPlan) {
      return;
    }

    const updated = await run(`task-${taskId}`, () =>
      api.updateTaskStatus(taskId, status)
    );
    if (updated) {
      setTaskCache((current) => ({
        ...current,
        [selectedPlan.id]: (current[selectedPlan.id] ?? []).map((task) =>
          task.id === taskId ? updated : task
        )
      }));
    }
  }

  async function handleReview() {
    if (!selectedPlan) {
      return;
    }
    const created = await run("review", () =>
      api.createReview(selectedPlan.id, feedback)
    );
    if (created) {
      setReview(created);
    }
  }

  async function handleAdjust() {
    if (!goal || !selectedPlan) {
      return;
    }
    const created = await run("adjust", () =>
      api.adjustTomorrow(goal.id, selectedPlan.day_index)
    );
    if (created) {
      setAdjustment(created);
      const refreshed = await api.getGoal(goal.id);
      setGoal(refreshed);
    }
  }

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
          <Badge tone="amber">
            {USE_ASYNC_JOBS ? "Celery Queue" : "Local Progress"}
          </Badge>
          <Badge tone="rose">Chroma Memory</Badge>
        </div>
      </header>

      {error ? (
        <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      <section className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Target className="h-5 w-5 text-primary" aria-hidden="true" />
                创建学习目标
              </CardTitle>
              <CardDescription>
                {USE_ASYNC_JOBS
                  ? "提交后会进入后台任务队列，完成后自动展示 Day 1 任务。"
                  : "本地模式会同步生成计划，并用前端进度条展示生成过程。"}
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
              <Button
                className="w-full"
                onClick={handleCreateGoal}
                disabled={isBusy}
              >
                {loadingStep === "goal" || isPlanGenerating ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Sparkles className="h-4 w-4" aria-hidden="true" />
                )}
                生成学习计划
              </Button>

              {planJob ? (
                <div className="space-y-3 rounded-md border bg-background p-4">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="font-medium">{getPlanJobLabel(planJob)}</span>
                    <Badge
                      tone={
                        planJob.status === "success"
                          ? "teal"
                          : planJob.status === "failed"
                            ? "rose"
                            : "amber"
                      }
                    >
                      {planJob.status}
                    </Badge>
                  </div>
                  <Progress value={planProgress} />
                  <p className="text-xs text-muted-foreground">
                    当前进度 {planProgress}%
                  </p>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileText className="h-5 w-5 text-primary" aria-hidden="true" />
                课程知识库
              </CardTitle>
              <CardDescription>
                上传课程资料后，任务生成会优先参考检索到的知识片段。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="material">课程资料</Label>
                <Input
                  id="material"
                  type="file"
                  accept=".pdf,.docx,.pptx,.txt,.md"
                  disabled={!goal || isBusy}
                  onChange={handleUploadMaterial}
                />
              </div>
              {materials.length > 0 ? (
                <div className="space-y-2">
                  {materials.map((material) => (
                    <div
                      className="rounded-md border bg-background p-3 text-sm"
                      key={material.id}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{material.filename}</span>
                        <Badge
                          tone={
                            material.parse_status === "ready"
                              ? "teal"
                              : material.parse_status === "failed"
                                ? "rose"
                                : "amber"
                          }
                        >
                          {material.parse_status}
                        </Badge>
                      </div>
                      <p className="mt-1 text-muted-foreground">
                        {material.chunk_count} chunks · {material.chroma_collection}
                      </p>
                      {material.error_message ? (
                        <p className="mt-2 text-rose-700">{material.error_message}</p>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState text="创建目标后可以上传课程资料。" />
              )}
              <div className="flex gap-2">
                <Input
                  value={knowledgeQuery}
                  onChange={(event) => setKnowledgeQuery(event.target.value)}
                  disabled={!goal || isBusy}
                />
                <Button
                  variant="outline"
                  onClick={handleSearchKnowledge}
                  disabled={!goal || isBusy}
                  title="检索知识库"
                >
                  <Search className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
              {knowledgeHits.length > 0 ? (
                <div className="space-y-2">
                  {knowledgeHits.map((hit, index) => (
                    <div className="rounded-md border bg-background p-3" key={index}>
                      <p className="line-clamp-4 text-sm leading-6 text-muted-foreground">
                        {hit.content}
                      </p>
                      <p className="mt-2 text-xs text-muted-foreground">
                        {String(hit.metadata.source ?? hit.metadata.filename ?? "material")}
                      </p>
                    </div>
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CalendarDays className="h-5 w-5 text-primary" aria-hidden="true" />
                学习计划
              </CardTitle>
              <CardDescription>
                选择任意一天即可查看或自动生成对应任务。
              </CardDescription>
            </CardHeader>
            <CardContent>
              {goal ? (
                <div className="grid gap-5 xl:grid-cols-[300px_1fr]">
                  <div className="space-y-2">
                    {plans.map((plan) => {
                      const isSelected = selectedPlan?.id === plan.id;
                      const hasTasks = Boolean(taskCache[plan.id]?.length);

                      return (
                        <button
                          className={cn(
                            "w-full rounded-md border bg-background p-3 text-left transition-colors hover:bg-muted",
                            isSelected && "border-primary bg-teal-50"
                          )}
                          key={plan.id}
                          onClick={() => selectPlan(plan)}
                          disabled={isBusy}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <Badge tone={plan.adjusted ? "amber" : "neutral"}>
                              Day {plan.day_index}
                            </Badge>
                            <span className="text-xs text-muted-foreground">
                              {plan.plan_date}
                            </span>
                          </div>
                          <h3 className="mt-3 text-sm font-semibold">{plan.topic}</h3>
                          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
                            {plan.objective}
                          </p>
                          <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                            <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
                            {hasTasks ? "任务已加载" : "按需生成"}
                          </div>
                        </button>
                      );
                    })}
                  </div>

                  <div className="rounded-md border bg-background p-4">
                    {selectedPlan ? (
                      <div className="space-y-4">
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                          <div>
                            <Badge tone={selectedPlan.adjusted ? "amber" : "teal"}>
                              Day {selectedPlan.day_index}
                            </Badge>
                            <h2 className="mt-3 text-lg font-semibold">
                              {selectedPlan.topic}
                            </h2>
                            <p className="mt-2 text-sm leading-6 text-muted-foreground">
                              {selectedPlan.objective}
                            </p>
                          </div>
                          <span className="text-sm text-muted-foreground">
                            {selectedPlan.plan_date}
                          </span>
                        </div>

                        <div className="space-y-2">
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-muted-foreground">任务完成度</span>
                            <span className="font-medium">{completionRate}%</span>
                          </div>
                          <Progress value={completionRate} />
                        </div>

                        {selectedTaskLoading ? (
                          <div className="flex min-h-48 items-center justify-center rounded-md border border-dashed">
                            <div className="flex items-center gap-2 text-sm text-muted-foreground">
                              <Loader2
                                className="h-4 w-4 animate-spin"
                                aria-hidden="true"
                              />
                              正在生成 Day {selectedPlan.day_index} 任务
                            </div>
                          </div>
                        ) : selectedTasks.length > 0 ? (
                          <div className="space-y-3">
                            {selectedTasks.map((task) => (
                              <div
                                className="rounded-md border bg-card p-4"
                                key={task.id}
                              >
                                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                                  <div>
                                    <div className="flex flex-wrap items-center gap-2">
                                      <h3 className="text-sm font-semibold">
                                        {task.title}
                                      </h3>
                                      <Badge tone={statusTone[task.status] ?? "neutral"}>
                                        {statusLabels[task.status] ?? task.status}
                                      </Badge>
                                    </div>
                                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                                      {task.description}
                                    </p>
                                  </div>
                                  <Badge tone="teal">
                                    {task.estimated_minutes} 分钟
                                  </Badge>
                                </div>
                                <div className="mt-4 flex flex-wrap gap-2">
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => handleUpdateTask(task.id, "done")}
                                    disabled={isBusy}
                                    title="标记完成"
                                  >
                                    <Check
                                      className="h-3.5 w-3.5"
                                      aria-hidden="true"
                                    />
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
                          <EmptyState text="当前日期还没有任务。" />
                        )}
                      </div>
                    ) : (
                      <EmptyState text="创建目标后会显示每日计划。" />
                    )}
                  </div>
                </div>
              ) : (
                <EmptyState text="创建目标后会显示完整时间线。" />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <RefreshCcw className="h-5 w-5 text-primary" aria-hidden="true" />
                复盘与调整
              </CardTitle>
              <CardDescription>
                当前选中 Day 会作为复盘对象，调整会作用到下一天计划。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="feedback">学习反馈</Label>
                <Textarea
                  id="feedback"
                  value={feedback}
                  onChange={(event) => setFeedback(event.target.value)}
                />
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Button onClick={handleReview} disabled={!selectedPlan || isBusy}>
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
                  调整下一天计划
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>

              {review ? (
                <div className="rounded-md border bg-background p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="text-sm font-semibold">AI 复盘</h3>
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
                    下一天计划调整
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
