"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BrainCircuit,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  FileText,
  FolderOpen,
  Languages,
  Loader2,
  RefreshCcw,
  Sparkles,
  Target,
  Trash2,
  ZoomIn,
  ZoomOut
} from "lucide-react";
import { api } from "@/lib/api";
import { ChatDrawer } from "@/components/chat-drawer";
import type { DrawerPanel } from "@/components/chat-drawer";
import { TaskQuizDialog } from "@/components/task-quiz-dialog";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkMath from "remark-math";
import type {
  Adjustment,
  CourseMaterial,
  GoalDetail,
  GoalSummary,
  Job,
  PdfMeta,
  PdfPageText,
  PdfPageTranslation,
  ReadingContext,
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
const LAST_GOAL_ID_KEY = "studyagent:lastGoalId";
const SELECTED_PLAN_PREFIX = "studyagent:selectedPlanId:";

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

function selectedPlanStorageKey(goalId: number) {
  return `${SELECTED_PLAN_PREFIX}${goalId}`;
}

export default function Home() {
  const [goalSummaries, setGoalSummaries] = useState<GoalSummary[]>([]);
  const [goal, setGoal] = useState<GoalDetail | null>(null);
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null);
  const [taskCache, setTaskCache] = useState<Record<number, StudyTask[]>>({});
  const [review, setReview] = useState<Review | null>(null);
  const [adjustment, setAdjustment] = useState<Adjustment | null>(null);
  const [materials, setMaterials] = useState<CourseMaterial[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [feedback, setFeedback] = useState("");
  const [quizTask, setQuizTask] = useState<StudyTask | null>(null);
  const [planJob, setPlanJob] = useState<Job | null>(null);
  const [loadingStep, setLoadingStep] = useState<string | null>(null);
  const [loadingGoals, setLoadingGoals] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestedPanel, setRequestedPanel] = useState<DrawerPanel | null>(null);
  const [activeView, setActiveView] = useState<"plan" | "reader">("plan");
  const [readerMaterialId, setReaderMaterialId] = useState<number | null>(null);
  const [pdfMeta, setPdfMeta] = useState<PdfMeta | null>(null);
  const [pdfPage, setPdfPage] = useState(1);
  const [pdfZoom, setPdfZoom] = useState(100);
  const [pdfText, setPdfText] = useState<PdfPageText | null>(null);
  const [pdfTranslation, setPdfTranslation] = useState<PdfPageTranslation | null>(null);
  const [readerLoading, setReaderLoading] = useState<string | null>(null);
  const [readerError, setReaderError] = useState<string | null>(null);

  const [form, setForm] = useState({
    title: "",
    goalType: "exam" as "exam" | "duration",
    examDate: formatDateInput(defaultExamDate),
    durationDays: 30,
    dailyMinutes: 120,
    currentLevel: "一般",
    keyTopics: ""
  });

  const plans = useMemo(() => sortPlans(goal?.plans ?? []), [goal]);
  const pdfMaterials = useMemo(
    () => materials.filter((item) => item.file_type.toLowerCase() === "pdf"),
    [materials]
  );
  const readingContext: ReadingContext | null =
    activeView === "reader" && readerMaterialId
      ? { material_id: readerMaterialId, page_index: pdfPage }
      : null;
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
  const isBusy = loadingStep !== null || isPlanGenerating || loadingGoals;

  useEffect(() => {
    void loadGoalSummaries(true);
    // 只在页面首次加载时恢复历史计划。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (activeView !== "reader") {
      return;
    }
    if (readerMaterialId && !pdfMaterials.some((item) => item.id === readerMaterialId)) {
      setReaderMaterialId(pdfMaterials[0]?.id ?? null);
      setPdfPage(1);
      return;
    }
    if (!readerMaterialId && pdfMaterials.length > 0) {
      setReaderMaterialId(pdfMaterials[0].id);
    }
  }, [activeView, pdfMaterials, readerMaterialId]);

  useEffect(() => {
    if (!readerMaterialId) {
      setPdfMeta(null);
      setPdfText(null);
      setPdfTranslation(null);
      return;
    }

    let cancelled = false;
    setReaderLoading("meta");
    setReaderError(null);
    api
      .getPdfMeta(readerMaterialId)
      .then((meta) => {
        if (cancelled) {
          return;
        }
        setPdfMeta(meta);
        setPdfPage((current) => Math.min(Math.max(current, 1), meta.page_count || 1));
      })
      .catch((err) => {
        if (!cancelled) {
          setReaderError(err instanceof Error ? err.message : "PDF 元信息加载失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setReaderLoading((current) => (current === "meta" ? null : current));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [readerMaterialId]);

  useEffect(() => {
    if (!readerMaterialId || !pdfMeta) {
      return;
    }

    let cancelled = false;
    setReaderLoading("text");
    setReaderError(null);
    setPdfTranslation(null);
    api
      .getPdfPageText(readerMaterialId, pdfPage)
      .then((pageText) => {
        if (!cancelled) {
          setPdfText(pageText);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setReaderError(err instanceof Error ? err.message : "PDF 文本加载失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setReaderLoading((current) => (current === "text" ? null : current));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [pdfMeta, pdfPage, readerMaterialId]);

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

  async function selectPlan(plan: StudyPlan, ownerGoalId = goal?.id) {
    setSelectedPlanId(plan.id);
    if (ownerGoalId) {
      window.localStorage.setItem(LAST_GOAL_ID_KEY, String(ownerGoalId));
      window.localStorage.setItem(selectedPlanStorageKey(ownerGoalId), String(plan.id));
    }
    setReview(null);
    setAdjustment(null);
    await ensureTasksForPlan(plan);
  }

  async function loadGoalSummaries(restoreLastGoal = false) {
    setLoadingGoals(true);
    setError(null);
    try {
      const summaries = await api.listGoals();
      setGoalSummaries(summaries);

      if (restoreLastGoal && summaries.length > 0) {
        const storedGoalId = Number(window.localStorage.getItem(LAST_GOAL_ID_KEY));
        const target = summaries.find((item) => item.id === storedGoalId) ?? summaries[0];
        await openGoal(target.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "历史计划加载失败");
    } finally {
      setLoadingGoals(false);
    }
  }

  async function openGoal(goalId: number) {
    setLoadingStep(`goal-${goalId}`);
    setError(null);
    try {
      const detail = await api.getGoal(goalId);
      const storedPlanId = Number(
        window.localStorage.getItem(selectedPlanStorageKey(goalId))
      );
      const orderedPlans = sortPlans(detail.plans);
      const plan =
        orderedPlans.find((item) => item.id === storedPlanId) ?? orderedPlans[0] ?? null;

      setGoal(detail);
      setTaskCache({});
      setReview(null);
      setAdjustment(null);
      setSelectedFiles([]);
      window.localStorage.setItem(LAST_GOAL_ID_KEY, String(goalId));

      const nextMaterials = await api.listMaterials(goalId);
      setMaterials(nextMaterials);

      if (plan) {
        await selectPlan(plan, detail.id);
      } else {
        setSelectedPlanId(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "计划加载失败");
    } finally {
      setLoadingStep(null);
    }
  }

  async function refreshWorkspace() {
    if (!goal) {
      await loadGoalSummaries(false);
      return;
    }

    const [detail, nextMaterials, summaries] = await Promise.all([
      api.getGoal(goal.id),
      api.listMaterials(goal.id),
      api.listGoals()
    ]);
    setGoal(detail);
    setMaterials(nextMaterials);
    setGoalSummaries(summaries);
  }

  async function handleDeleteGoal(goalId: number) {
    const confirmed = window.confirm("确定删除这个学习计划吗？计划、任务和知识库索引都会被移除。");
    if (!confirmed) {
      return;
    }

    setLoadingStep(`delete-${goalId}`);
    setError(null);
    try {
      await api.deleteGoal(goalId);
      window.localStorage.removeItem(selectedPlanStorageKey(goalId));
      if (goal?.id === goalId) {
        window.localStorage.removeItem(LAST_GOAL_ID_KEY);
        setGoal(null);
        setSelectedPlanId(null);
        setTaskCache({});
        setReview(null);
        setAdjustment(null);
        setMaterials([]);
      }

      const nextSummaries = await api.listGoals();
      setGoalSummaries(nextSummaries);
      if (goal?.id === goalId && nextSummaries.length > 0) {
        await openGoal(nextSummaries[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除计划失败");
    } finally {
      setLoadingStep(null);
    }
  }

  async function handleRegeneratePlan() {
    if (!goal) {
      return;
    }
    const confirmed = window.confirm(
      "确定基于当前 RAG 知识库重新生成学习计划吗？现有每日计划、任务、小测、复盘和调整记录会被替换。"
    );
    if (!confirmed) {
      return;
    }

    setLoadingStep("regenerate-plan");
    setError(null);
    try {
      const regeneratedGoal = await api.regenerateGoalPlan(goal.id);
      const nextMaterials = await api.listMaterials(goal.id);
      const nextSummaries = await api.listGoals();
      const firstPlan = sortPlans(regeneratedGoal.plans)[0] ?? null;

      setGoal(regeneratedGoal);
      setMaterials(nextMaterials);
      setGoalSummaries(nextSummaries);
      setTaskCache({});
      setReview(null);
      setAdjustment(null);

      if (firstPlan) {
        setSelectedPlanId(firstPlan.id);
        window.localStorage.setItem(
          selectedPlanStorageKey(regeneratedGoal.id),
          String(firstPlan.id)
        );
        await ensureTasksForPlan(firstPlan);
      } else {
        setSelectedPlanId(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "计划重新生成失败");
    } finally {
      setLoadingStep(null);
    }
  }

  function handleGoalFiles(event: React.ChangeEvent<HTMLInputElement>) {
    setSelectedFiles(Array.from(event.target.files ?? []));
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
    setPlanJob(null);
    setError(null);
    setLoadingStep("goal");

    const payload = {
      title: form.title,
      goal_type: form.goalType,
      exam_date: form.goalType === "exam" ? form.examDate : null,
      duration_days: form.goalType === "duration" ? Number(form.durationDays) : null,
      daily_minutes: Number(form.dailyMinutes),
      current_level: form.currentLevel,
      key_topics: keyTopics
    };

    try {
      let createdGoal: GoalDetail;

      if (USE_ASYNC_JOBS && selectedFiles.length === 0) {
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
          createdGoal = await api.createGoalWithMaterials(payload, selectedFiles);
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
      setMaterials(await api.listMaterials(createdGoal.id));
      await loadGoalSummaries(false);
      window.localStorage.setItem(LAST_GOAL_ID_KEY, String(createdGoal.id));

      const firstPlan = sortPlans(createdGoal.plans)[0];
      if (firstPlan) {
        await selectPlan(firstPlan, createdGoal.id);
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

  function handleReaderMaterialChange(materialId: number) {
    if (materialId === readerMaterialId) {
      return;
    }
    setReaderMaterialId(materialId);
    setPdfPage(1);
    setPdfMeta(null);
    setPdfText(null);
    setPdfTranslation(null);
    setReaderError(null);
  }

  async function handleTranslatePdfPage() {
    if (!readerMaterialId || !pdfText?.readable) {
      return;
    }
    setReaderLoading("translate");
    setReaderError(null);
    try {
      const translated = await api.translatePdfPage(readerMaterialId, pdfPage);
      setPdfTranslation(translated);
    } catch (err) {
      setReaderError(err instanceof Error ? err.message : "当前页翻译失败");
    } finally {
      setReaderLoading((current) => (current === "translate" ? null : current));
    }
  }

  async function handleReaderPdfUpload(event: React.ChangeEvent<HTMLInputElement>) {
    if (!goal || !event.target.files?.[0]) {
      event.target.value = "";
      return;
    }
    const file = event.target.files[0];
    setReaderLoading("upload");
    setReaderError(null);
    try {
      const material = await api.uploadReaderPdf(goal.id, file);
      const nextMaterials = await api.listMaterials(goal.id);
      setMaterials(nextMaterials);
      setReaderMaterialId(material.id);
      setPdfPage(1);
      setPdfMeta(null);
      setPdfText(null);
      setPdfTranslation(null);
      await loadGoalSummaries(false);
    } catch (err) {
      setReaderError(err instanceof Error ? err.message : "PDF 上传失败");
    } finally {
      event.target.value = "";
      setReaderLoading((current) => (current === "upload" ? null : current));
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-6 px-4 py-6 md:px-8">
      <header className="flex flex-col gap-4 border-b pb-5 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium text-primary">
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            <span>LearnFlow</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-normal md:text-3xl">
            从目标到复盘的学习执行工作台
          </h1>
        </div>
        <div className="flex flex-col items-start gap-2 md:items-end">
          <div className="flex w-fit rounded-md border bg-background p-1">
            {[
              { label: "生成计划", value: "plan" as const },
              { label: "资料阅读", value: "reader" as const }
            ].map((item) => (
              <button
                className={cn(
                  "h-8 rounded px-3 text-xs font-medium transition-colors",
                  activeView === item.value
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted"
                )}
                key={item.value}
                type="button"
                onClick={() => setActiveView(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone="teal">LangGraph Agent</Badge>
            <Badge tone="amber">
              {USE_ASYNC_JOBS ? "Celery Queue" : "Local Progress"}
            </Badge>
            <Badge tone="rose">Chroma Memory</Badge>
          </div>
        </div>
      </header>

      {error ? (
        <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      {activeView === "plan" ? (
      <section className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FolderOpen className="h-5 w-5 text-primary" aria-hidden="true" />
                我的学习计划
              </CardTitle>
              <CardDescription>
                已生成的计划会保存在本地数据库，点击即可继续学习。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {loadingGoals ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  正在加载历史计划
                </div>
              ) : goalSummaries.length > 0 ? (
                <div className="max-h-[340px] space-y-2 overflow-y-auto pr-1">
                  {goalSummaries.map((item) => {
                    const active = goal?.id === item.id;
                    return (
                      <div
                        className={cn(
                          "rounded-md border bg-background p-3",
                          active && "border-primary bg-teal-50"
                        )}
                        key={item.id}
                      >
                        <div className="flex items-start gap-2">
                          <button
                            className="min-w-0 flex-1 text-left"
                            disabled={isBusy}
                            onClick={() => openGoal(item.id)}
                          >
                            <div className="flex items-center gap-2">
                              <h3 className="truncate text-sm font-semibold">
                                {item.title}
                              </h3>
                              {active ? <Badge tone="teal">当前</Badge> : null}
                            </div>
                            <p className="mt-1 text-xs text-muted-foreground">
                              {item.goal_type === "duration"
                                ? `${item.duration_days ?? item.plan_count} 天周期`
                                : `考试 ${item.exam_date}`}{" "}
                              · {item.plan_count} 天计划
                            </p>
                            <p className="mt-1 text-xs text-muted-foreground">
                              资料 {item.material_count} 份 · {item.status}
                            </p>
                          </button>
                          <Button
                            size="icon"
                            variant="ghost"
                            title="删除计划"
                            disabled={isBusy}
                            onClick={() => handleDeleteGoal(item.id)}
                          >
                            {loadingStep === `delete-${item.id}` ? (
                              <Loader2
                                className="h-4 w-4 animate-spin"
                                aria-hidden="true"
                              />
                            ) : (
                              <Trash2 className="h-4 w-4" aria-hidden="true" />
                            )}
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <EmptyState text="还没有历史计划，生成后会自动出现在这里。" />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Target className="h-5 w-5 text-primary" aria-hidden="true" />
                创建学习目标
              </CardTitle>
              <CardDescription>
                {USE_ASYNC_JOBS
                  ? "未上传资料时走后台队列；上传资料时会先同步建库再生成计划。"
                  : "可先上传课程资料，本地模式会先建库再生成计划。"}
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
                  {form.goalType === "exam" ? (
                    <>
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
                    </>
                  ) : (
                    <>
                      <Label htmlFor="durationDays">学习周期</Label>
                      <Input
                        id="durationDays"
                        type="number"
                        min={3}
                        max={120}
                        value={form.durationDays}
                        onChange={(event) =>
                          setForm((current) => ({
                            ...current,
                            durationDays: Number(event.target.value)
                          }))
                        }
                      />
                    </>
                  )}
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
              <div className="grid grid-cols-[minmax(0,1fr)_172px] gap-3">
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
                  <Label>目标模式</Label>
                  <div className="grid h-10 grid-cols-2 rounded-md border bg-background p-1">
                    {[
                      { label: "考试", value: "exam" as const },
                      { label: "周期", value: "duration" as const }
                    ].map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className={cn(
                          "rounded px-2 text-xs font-medium transition-colors",
                          form.goalType === option.value
                            ? "bg-primary text-primary-foreground"
                            : "text-muted-foreground hover:bg-muted"
                        )}
                        onClick={() =>
                          setForm((current) => ({
                            ...current,
                            goalType: option.value
                          }))
                        }
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
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
              <div className="space-y-2">
                <Label htmlFor="goalMaterials">课程资料</Label>
                <Input
                  id="goalMaterials"
                  type="file"
                  multiple
                  accept=".pdf,.docx,.pptx,.txt,.md"
                  disabled={isBusy}
                  onChange={handleGoalFiles}
                />
                {selectedFiles.length > 0 ? (
                  <div className="space-y-2 rounded-md border bg-background p-3">
                    {selectedFiles.map((file) => (
                      <div
                        className="flex items-center justify-between gap-3 text-xs text-muted-foreground"
                        key={`${file.name}-${file.lastModified}`}
                      >
                        <span className="truncate">{file.name}</span>
                        <span>{Math.max(1, Math.round(file.size / 1024))} KB</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs leading-5 text-muted-foreground">
                    可选：上传 PDF、PPTX、DOCX、TXT 或 MD，计划会优先参考资料内容。
                  </p>
                )}
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
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <CalendarDays className="h-5 w-5 text-primary" aria-hidden="true" />
                    学习计划
                  </CardTitle>
                  <CardDescription>
                    选择任意一天即可查看或自动生成对应任务。
                  </CardDescription>
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  title="基于更新后的 RAG 知识库重新生成计划"
                  disabled={!goal || isBusy}
                  onClick={handleRegeneratePlan}
                >
                  {loadingStep === "regenerate-plan" ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                  )}
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {goal ? (
                <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)] xl:items-stretch">
                  <div className="h-[calc(100vh-160px)] min-h-[775px] space-y-2 overflow-y-auto pr-1">
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

                  <div className="flex h-[calc(100vh-160px)] min-h-[775px] flex-col overflow-hidden rounded-md border bg-background p-4">
                    {selectedPlan ? (
                      <div className="flex min-h-0 flex-1 flex-col">
                        <div className="shrink-0 space-y-4 pb-4">
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
                        </div>

                        {selectedTaskLoading ? (
                          <div className="flex min-h-0 flex-1 items-center justify-center rounded-md border border-dashed">
                            <div className="flex items-center gap-2 text-sm text-muted-foreground">
                              <Loader2
                                className="h-4 w-4 animate-spin"
                                aria-hidden="true"
                              />
                              正在生成 Day {selectedPlan.day_index} 任务
                            </div>
                          </div>
                        ) : selectedTasks.length > 0 ? (
                          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
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
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => setQuizTask(task)}
                                    disabled={selectedTaskLoading}
                                    title="开始答题"
                                  >
                                    <BrainCircuit
                                      className="h-3.5 w-3.5"
                                      aria-hidden="true"
                                    />
                                    开始答题
                                  </Button>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="min-h-0 flex-1">
                            <EmptyState text="当前日期还没有任务。" />
                          </div>
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
                <FileText className="h-5 w-5 text-primary" aria-hidden="true" />
                知识库状态
              </CardTitle>
              <CardDescription>
                素材上传、手动插入和 RAG 检索已整合到右侧知识库面板。
              </CardDescription>
            </CardHeader>
            <CardContent>
              {goal ? (
                <div className="grid grid-cols-3 gap-2 text-center text-sm">
                  <div className="rounded-md border bg-background p-3">
                    <p className="text-lg font-semibold">{materials.length}</p>
                    <p className="mt-1 text-xs text-muted-foreground">素材</p>
                  </div>
                  <div className="rounded-md border bg-background p-3">
                    <p className="text-lg font-semibold">
                      {materials.filter((item) => item.parse_status === "ready").length}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">ready</p>
                  </div>
                  <div className="rounded-md border bg-background p-3">
                    <p className="text-lg font-semibold">
                      {materials.reduce((total, item) => total + item.chunk_count, 0)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">chunks</p>
                  </div>
                </div>
              ) : (
                <EmptyState text="创建或打开学习目标后，可以管理对应知识库。" />
              )}
            </CardContent>
          </Card>
        </div>
      </section>
      ) : (
        <PdfReaderView
          error={readerError}
          loading={readerLoading}
          materials={pdfMaterials}
          meta={pdfMeta}
          page={pdfPage}
          pageText={pdfText}
          selectedMaterialId={readerMaterialId}
          translation={pdfTranslation}
          zoom={pdfZoom}
          onMaterialChange={handleReaderMaterialChange}
          onPageChange={setPdfPage}
          onUpload={handleReaderPdfUpload}
          onTranslate={handleTranslatePdfPage}
          onZoomChange={setPdfZoom}
        />
      )}
      <TaskQuizDialog
        open={Boolean(quizTask)}
        task={quizTask}
        onClose={() => setQuizTask(null)}
      />
      <ChatDrawer
        adjustment={adjustment}
        currentMaterials={materials}
        feedback={feedback}
        goal={goal}
        goalSummaries={goalSummaries}
        isBusy={isBusy}
        loadingStep={loadingStep}
        readingContext={readingContext}
        requestedPanel={requestedPanel}
        review={review}
        selectedPlan={selectedPlan}
        selectedTasks={selectedTasks}
        onAdjustPlan={handleAdjust}
        onCreateReview={handleReview}
        onFeedbackChange={setFeedback}
        onRequestedPanelHandled={() => setRequestedPanel(null)}
        onWorkspaceChange={refreshWorkspace}
      />
    </main>
  );
}

function PdfReaderView({
  error,
  loading,
  materials,
  meta,
  page,
  pageText,
  selectedMaterialId,
  translation,
  zoom,
  onMaterialChange,
  onPageChange,
  onUpload,
  onTranslate,
  onZoomChange
}: {
  error: string | null;
  loading: string | null;
  materials: CourseMaterial[];
  meta: PdfMeta | null;
  page: number;
  pageText: PdfPageText | null;
  selectedMaterialId: number | null;
  translation: PdfPageTranslation | null;
  zoom: number;
  onMaterialChange: (materialId: number) => void;
  onPageChange: (page: number) => void;
  onUpload: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onTranslate: () => Promise<void>;
  onZoomChange: (zoom: number) => void;
}) {
  const selectedMaterial = materials.find((item) => item.id === selectedMaterialId) ?? null;
  const pageCount = meta?.page_count ?? 1;
  const readable = Boolean(pageText?.readable);
  const [readerPanel, setReaderPanel] = useState<"materials" | "translation" | null>(null);
  const [pageInput, setPageInput] = useState(String(page));

  useEffect(() => {
    setPageInput(String(page));
  }, [page]);

  function movePage(offset: number) {
    onPageChange(Math.min(Math.max(page + offset, 1), pageCount));
  }

  function jumpToInputPage() {
    const nextPage = Number(pageInput);
    if (!Number.isFinite(nextPage)) {
      setPageInput(String(page));
      return;
    }
    onPageChange(Math.min(Math.max(Math.round(nextPage), 1), pageCount));
  }

  function toggleReaderPanel(panel: "materials" | "translation") {
    setReaderPanel((current) => (current === panel ? null : panel));
  }

  async function translateAndOpenPanel() {
    setReaderPanel("translation");
    await onTranslate();
  }

  return (
    <section>
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <FileText className="h-5 w-5 text-primary" aria-hidden="true" />
                资料阅读
              </CardTitle>
              <CardDescription>
                {selectedMaterial
                  ? `${selectedMaterial.filename} · 第 ${page} 页`
                  : "选择右侧资料面板中的 PDF 开始阅读"}
              </CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <Input
                  className="h-8 w-20"
                  min={1}
                  max={pageCount}
                  type="number"
                  value={pageInput}
                  disabled={!meta}
                  onChange={(event) => setPageInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      jumpToInputPage();
                    }
                  }}
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!meta}
                  onClick={jumpToInputPage}
                >
                  跳转
                </Button>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={!meta || page <= 1}
                onClick={() => movePage(-1)}
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                上一页
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!meta || page >= pageCount}
                onClick={() => movePage(1)}
              >
                下一页
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {error ? (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border bg-background p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={readable ? "teal" : "amber"}>
                {readable ? "文本可读取" : "当前页无可提取文本"}
              </Badge>
              {meta ? (
                <span className="text-sm text-muted-foreground">
                  {page} / {meta.page_count} 页
                </span>
              ) : null}
              {loading === "meta" || loading === "text" ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="icon"
                variant="outline"
                title="缩小"
                onClick={() => onZoomChange(Math.max(60, zoom - 10))}
              >
                <ZoomOut className="h-4 w-4" aria-hidden="true" />
              </Button>
              <span className="w-14 text-center text-sm text-muted-foreground">
                {zoom}%
              </span>
              <Button
                size="icon"
                variant="outline"
                title="放大"
                onClick={() => onZoomChange(Math.min(180, zoom + 10))}
              >
                <ZoomIn className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                size="sm"
                disabled={!readable || loading === "translate"}
                onClick={() => void translateAndOpenPanel()}
                title="翻译当前页"
              >
                {loading === "translate" ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Languages className="h-4 w-4" aria-hidden="true" />
                )}
                翻译当前页
              </Button>
            </div>
          </div>

          <div className="relative grid min-h-[900px] gap-3 overflow-hidden xl:grid-cols-[minmax(0,1fr)_48px]">
            {selectedMaterialId && meta ? (
              <div className="min-h-[820px] overflow-auto rounded-md border bg-slate-100 p-4">
                <img
                  alt={`${meta.filename} 第 ${page} 页`}
                  className="mx-auto max-w-none rounded-sm border bg-white shadow-sm"
                  src={api.pdfPageImageUrl(selectedMaterialId, page)}
                  style={{ width: `${zoom}%` }}
                />
              </div>
            ) : (
              <div className="min-h-[820px]">
                <EmptyState text="选择一个 PDF 资料后会显示阅读器。" />
              </div>
            )}

            <div className="flex min-h-[820px] flex-col items-center gap-2 rounded-md border bg-background p-2">
              <Button
                size="icon"
                variant={readerPanel === "materials" ? "default" : "ghost"}
                title="PDF 资料"
                onClick={() => toggleReaderPanel("materials")}
              >
                <FileText className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                size="icon"
                variant={readerPanel === "translation" ? "default" : "ghost"}
                title="翻译对照"
                onClick={() => toggleReaderPanel("translation")}
              >
                <Languages className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>

            <div
              className={cn(
                "absolute inset-y-0 right-16 z-20 flex w-[360px] flex-col overflow-hidden rounded-md border bg-background shadow-xl transition-all duration-200",
                readerPanel
                  ? "translate-x-0 opacity-100"
                  : "pointer-events-none translate-x-[calc(100%+5rem)] opacity-0"
              )}
            >
                {readerPanel === "materials" ? (
                  <>
                    <div className="border-b p-4">
                      <h3 className="text-sm font-semibold">PDF 资料</h3>
                      <p className="mt-1 text-xs text-muted-foreground">
                        上传 PDF 到阅读器，或切换当前阅读资料。
                      </p>
                    </div>
                    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
                      <div className="rounded-md border bg-background p-3">
                        <Label htmlFor="readerPdfUpload">上传 PDF 到阅读器</Label>
                        <Input
                          id="readerPdfUpload"
                          className="mt-2"
                          type="file"
                          accept=".pdf,application/pdf"
                          disabled={loading === "upload"}
                          onChange={onUpload}
                        />
                        <p className="mt-2 text-xs leading-5 text-muted-foreground">
                          只保存为阅读资料，不进行 RAG 建库。
                        </p>
                        {loading === "upload" ? (
                          <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                            <Loader2
                              className="h-3.5 w-3.5 animate-spin"
                              aria-hidden="true"
                            />
                            正在上传 PDF
                          </div>
                        ) : null}
                      </div>
                      {materials.length > 0 ? (
                        <div className="space-y-2">
                          {materials.map((material) => {
                            const active = material.id === selectedMaterialId;
                            return (
                              <button
                                className={cn(
                                  "w-full rounded-md border bg-background p-3 text-left transition-colors hover:bg-muted",
                                  active && "border-primary bg-teal-50"
                                )}
                                key={material.id}
                                type="button"
                                onClick={() => onMaterialChange(material.id)}
                              >
                                <div className="flex items-start justify-between gap-2">
                                  <span className="line-clamp-2 text-sm font-semibold">
                                    {material.filename}
                                  </span>
                                  <Badge
                                    tone={
                                      material.parse_status === "ready"
                                        ? "teal"
                                        : "amber"
                                    }
                                  >
                                    {material.parse_status}
                                  </Badge>
                                </div>
                                <p className="mt-2 text-xs text-muted-foreground">
                                  {material.chunk_count} chunks · PDF
                                </p>
                              </button>
                            );
                          })}
                        </div>
                      ) : (
                        <EmptyState text="当前目标还没有 PDF 资料。" />
                      )}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="border-b p-4">
                      <h3 className="text-sm font-semibold">翻译对照</h3>
                      <p className="mt-1 text-xs text-muted-foreground">
                        右侧 AI 聊天会读取当前页可提取文本。
                      </p>
                    </div>
                    <div className="min-h-0 flex-1 overflow-y-auto p-4">
                      {!readable ? (
                        <div className="rounded-md border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
                          当前页没有可提取文本，可能是扫描版或图片型 PDF。第一版暂不处理 OCR。
                        </div>
                      ) : translation ? (
                        <div className="space-y-3">
                          <Badge tone={translation.cached ? "neutral" : "teal"}>
                            {translation.cached ? "缓存翻译" : "新翻译"}
                          </Badge>
                          <ReaderMarkdown content={translation.translated_text} />
                        </div>
                      ) : (
                        <div className="space-y-4">
                          <div className="rounded-md border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
                            点击“翻译当前页”后显示中文对照。
                          </div>
                          <div>
                            <h4 className="mb-2 text-sm font-semibold">
                              当前页原文预览
                            </h4>
                            <ReaderMarkdown
                              className="line-clamp-[16] text-muted-foreground"
                              content={pageText?.text ?? ""}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

function ReaderMarkdown({
  className,
  content
}: {
  className?: string;
  content: string;
}) {
  return (
    <div className={cn("chat-markdown text-sm leading-7", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          code: ({ className, children, ...props }) => {
            const isBlock =
              /language-/.test(className ?? "") || String(children).includes("\n");
            if (!isBlock) {
              return (
                <code
                  className="rounded bg-muted px-1 py-0.5 font-mono text-[0.92em]"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <code className={cn("block font-mono text-xs", className)} {...props}>
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre className="overflow-x-auto rounded-md border bg-slate-950 p-3 text-slate-50">
              {children}
            </pre>
          ),
          ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-primary/50 pl-3 text-muted-foreground">
              {children}
            </blockquote>
          )
        }}
      >
        {normalizeReaderMarkdown(content)}
      </ReactMarkdown>
    </div>
  );
}

function normalizeReaderMarkdown(content: string) {
  return content
    .replace(/\\\[((?:.|\n)*?)\\\]/g, (_, formula: string) => `\n$$\n${formula.trim()}\n$$\n`)
    .replace(/\\\(((?:.|\n)*?)\\\)/g, (_, formula: string) => `$${formula.trim()}$`);
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex min-h-32 items-center justify-center rounded-md border border-dashed bg-background px-4 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}
