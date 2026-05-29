"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BrainCircuit,
  CheckCircle2,
  Loader2,
  RefreshCcw,
  Send,
  X,
  XCircle
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  QuizAnswerItem,
  QuizQuestion,
  QuizResultItem,
  StudyTask,
  TaskQuiz
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

type TaskQuizDialogProps = {
  open: boolean;
  task: StudyTask | null;
  onClose: () => void;
};

export function TaskQuizDialog({ open, task, onClose }: TaskQuizDialogProps) {
  const [quiz, setQuiz] = useState<TaskQuiz | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resultMap = useMemo(() => {
    const items = quiz?.result?.items ?? [];
    return Object.fromEntries(items.map((item) => [item.question_id, item]));
  }, [quiz]);

  useEffect(() => {
    if (!open || !task) {
      return;
    }
    void loadQuiz(false);
    // task.id 变化时才重新拉取，避免用户输入答案时触发重复请求。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, task?.id]);

  if (!open || !task) {
    return null;
  }

  async function loadQuiz(regenerate: boolean) {
    if (!task) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const nextQuiz = await api.generateTaskQuiz(task.id, regenerate);
      setQuiz(nextQuiz);
      setAnswers(
        Object.fromEntries(
          (nextQuiz.answers ?? []).map((item) => [item.question_id, item.answer])
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "小测生成失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit() {
    if (!quiz) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const payload: QuizAnswerItem[] = quiz.questions.map((question) => ({
        question_id: question.id,
        answer: answers[question.id] ?? ""
      }));
      const nextQuiz = await api.submitTaskQuiz(quiz.id, payload);
      setQuiz(nextQuiz);
      setAnswers(
        Object.fromEntries(
          (nextQuiz.answers ?? []).map((item) => [item.question_id, item.answer])
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交批改失败");
    } finally {
      setSubmitting(false);
    }
  }

  function updateAnswer(questionId: string, value: string) {
    setAnswers((current) => ({ ...current, [questionId]: value }));
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 px-4 py-6"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-md border bg-background shadow-xl">
        <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <BrainCircuit className="h-5 w-5 text-primary" aria-hidden="true" />
              <h2 className="text-lg font-semibold">任务小测</h2>
              {quiz ? (
                <Badge tone={quiz.source_mode === "rag" ? "teal" : "amber"}>
                  {quiz.source_mode === "rag" ? "基于课程资料" : "基于任务主题"}
                </Badge>
              ) : null}
            </div>
            <p className="mt-1 truncate text-sm text-muted-foreground">
              {task.title}
            </p>
          </div>
          <Button size="icon" variant="ghost" onClick={onClose} title="关闭">
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>

        <div className="overflow-y-auto px-5 py-4">
          {error ? (
            <div className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {error}
            </div>
          ) : null}

          {loading ? (
            <div className="flex min-h-64 items-center justify-center rounded-md border border-dashed">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                正在生成任务小测
              </div>
            </div>
          ) : quiz ? (
            <div className="space-y-4">
              {quiz.questions.map((question, index) => (
                <QuestionBlock
                  answer={answers[question.id] ?? ""}
                  disabled={Boolean(quiz.result)}
                  key={question.id}
                  index={index}
                  onAnswer={(value) => updateAnswer(question.id, value)}
                  question={question}
                  result={resultMap[question.id]}
                />
              ))}

              {quiz.result ? (
                <div className="rounded-md border bg-teal-50 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <h3 className="text-sm font-semibold text-teal-900">批改结果</h3>
                    <Badge tone={quiz.result.score >= 60 ? "teal" : "rose"}>
                      约 {quiz.result.score} 分
                    </Badge>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-teal-900">
                    {quiz.result.summary}
                  </p>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="flex min-h-64 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
              暂无小测
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t px-5 py-4">
          <Button
            variant="outline"
            onClick={() => loadQuiz(true)}
            disabled={loading || submitting}
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
            )}
            重新出题
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              关闭
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={!quiz || Boolean(quiz.result) || submitting || loading}
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Send className="h-4 w-4" aria-hidden="true" />
              )}
              提交批改
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function QuestionBlock({
  answer,
  disabled,
  index,
  onAnswer,
  question,
  result
}: {
  answer: string;
  disabled: boolean;
  index: number;
  onAnswer: (value: string) => void;
  question: QuizQuestion;
  result?: QuizResultItem;
}) {
  return (
    <div className="rounded-md border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="neutral">第 {index + 1} 题</Badge>
            <Badge tone={question.type === "single_choice" ? "teal" : "amber"}>
              {question.type === "single_choice" ? "单选" : "简答"}
            </Badge>
          </div>
          <p className="mt-3 text-sm font-medium leading-6">{question.question}</p>
        </div>
        {result ? (
          <Badge tone={result.is_correct ? "teal" : "rose"}>
            {result.is_correct ? "正确" : "错误"} · {result.score}
          </Badge>
        ) : null}
      </div>

      {question.type === "single_choice" ? (
        <div className="mt-4 grid gap-2">
          {question.options.map((option) => (
            <label
              className={cn(
                "flex cursor-pointer items-start gap-2 rounded-md border bg-background px-3 py-2 text-sm leading-6",
                answer === option && "border-primary bg-teal-50",
                disabled && "cursor-default opacity-80"
              )}
              key={option}
            >
              <input
                checked={answer === option}
                className="mt-1"
                disabled={disabled}
                name={question.id}
                onChange={() => onAnswer(option)}
                type="radio"
              />
              <span>{option}</span>
            </label>
          ))}
        </div>
      ) : (
        <Textarea
          className="mt-4 min-h-24"
          disabled={disabled}
          onChange={(event) => onAnswer(event.target.value)}
          value={answer}
        />
      )}

      {result ? (
        <div className="mt-4 space-y-3 rounded-md border bg-background p-3 text-sm">
          <div className="flex items-center gap-2">
            {result.is_correct ? (
              <CheckCircle2 className="h-4 w-4 text-teal-700" aria-hidden="true" />
            ) : (
              <XCircle className="h-4 w-4 text-rose-700" aria-hidden="true" />
            )}
            <span className="font-medium">{result.feedback}</span>
          </div>
          {result.correct_answer ? (
            <p className="leading-6 text-muted-foreground">
              参考答案：{result.correct_answer}
            </p>
          ) : null}
          {question.explanation ? (
            <p className="leading-6 text-muted-foreground">
              解析：{question.explanation}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
