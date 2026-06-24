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
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
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
  const [aiGrading, setAiGrading] = useState(false);
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
      let nextQuiz: TaskQuiz;
      if (regenerate) {
        nextQuiz = await api.generateTaskQuiz(task.id, true);
      } else {
        try {
          nextQuiz = await api.getTaskQuiz(task.id);
        } catch {
          nextQuiz = await api.generateTaskQuiz(task.id, false);
        }
      }
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

  async function handleAiGrade() {
    if (!quiz) {
      return;
    }
    setAiGrading(true);
    setError(null);
    try {
      const payload: QuizAnswerItem[] = quiz.questions.map((question) => ({
        question_id: question.id,
        answer: answers[question.id] ?? ""
      }));
      const nextQuiz = await api.aiGradeTaskQuiz(quiz.id, payload);
      setQuiz(nextQuiz);
      setAnswers(
        Object.fromEntries(
          (nextQuiz.answers ?? []).map((item) => [item.question_id, item.answer])
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI 批改失败");
    } finally {
      setAiGrading(false);
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
      <div className="flex max-h-[94vh] w-full max-w-5xl flex-col overflow-hidden rounded-md border bg-background shadow-xl">
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
                  <div className="mt-2 text-sm leading-6 text-teal-900">
                    <MarkdownContent content={quiz.result.summary} />
                  </div>
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
            disabled={loading || submitting || aiGrading}
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
              variant="outline"
              onClick={handleAiGrade}
              disabled={!quiz || submitting || loading || aiGrading}
              title="调用 AI 批改主观题"
            >
              {aiGrading ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <BrainCircuit className="h-4 w-4" aria-hidden="true" />
              )}
              AI 批改
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={!quiz || Boolean(quiz.result) || submitting || loading || aiGrading}
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
          <div className="mt-3 text-sm font-medium leading-6">
            <MarkdownContent content={question.question} />
          </div>
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
              <MarkdownContent
                className="min-w-0 flex-1"
                content={option}
                inline
              />
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
            <div className="min-w-0 flex-1 font-medium">
              <MarkdownContent content={result.feedback} />
            </div>
          </div>
          {result.correct_answer ? (
            <div className="leading-6 text-muted-foreground">
              <span className="font-medium text-foreground">参考答案：</span>
              <MarkdownContent content={result.correct_answer} />
            </div>
          ) : null}
          {question.explanation ? (
            <div className="leading-6 text-muted-foreground">
              <span className="font-medium text-foreground">解析：</span>
              <MarkdownContent content={question.explanation} />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function MarkdownContent({
  className,
  content,
  inline = false
}: {
  className?: string;
  content: string;
  inline?: boolean;
}) {
  const Wrapper = inline ? "span" : "div";

  return (
    <Wrapper
      className={cn("chat-markdown quiz-markdown", inline && "inline-markdown", className)}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          p: ({ children }) => (inline ? <span>{children}</span> : <p>{children}</p>),
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
        {normalizeQuizMarkdown(content)}
      </ReactMarkdown>
    </Wrapper>
  );
}

function normalizeQuizMarkdown(content: string) {
  const mathNormalized = normalizeAccidentalIndentedMarkdown(
    normalizeCompactMarkdownTables(content)
  )
    .replace(/\\\[((?:.|\n)*?)\\\]/g, (_, formula: string) => `\n$$\n${formula.trim()}\n$$\n`)
    .replace(/\\\(((?:.|\n)*?)\\\)/g, (_, formula: string) => `$${formula.trim()}$`);

  // 已经含有标准 LaTeX 分隔符时，避免再做启发式替换造成嵌套。
  if (mathNormalized.includes("$")) {
    return mathNormalized;
  }

  return mathNormalized
    .replace(
      /\b([A-Za-z])\s*=\s*\[\[\s*([^,\]\[]+)\s*,\s*([^\]\[]+?)\s*\]\s*,\s*\[\s*([^,\]\[]+)\s*,\s*([^\]\[]+?)\s*\]\]/g,
      (
        _,
        name: string,
        a11: string,
        a12: string,
        a21: string,
        a22: string
      ) => {
        return `$${name} = \\begin{pmatrix} ${a11.trim()} & ${a12.trim()} \\\\ ${a21.trim()} & ${a22.trim()} \\end{pmatrix}$`;
      }
    )
    .replace(/\|\|([^|\n]{1,60})\|\|_([0-9A-Za-z∞]+)/g, (_, body: string, norm: string) => {
      return `$\\|${body.trim()}\\|_${norm}$`;
    })
    .replace(
      /(^|[^\\|])\|([^|\n]{1,60})\|_([0-9A-Za-z∞]+)/g,
      (_, prefix: string, body: string, norm: string) => {
        return `${prefix}$\\|${body.trim()}\\|_${norm}$`;
      }
    )
    .replace(/\b([A-Za-z])\^T\s*([A-Za-z])\b/g, (_, left: string, right: string) => {
      return `$${left}^T ${right}$`;
    })
    .replace(/sqrt\(lambda_max\)/gi, "$\\sqrt{\\lambda_{\\max}}$")
    .replace(/lambda_max/gi, "$\\lambda_{\\max}$");
}

function normalizeCompactMarkdownTables(content: string) {
  return content
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();
      const pipeCount = (trimmed.match(/\|/g) ?? []).length;
      const looksLikeCompactTable =
        trimmed.startsWith("|") && pipeCount >= 8 && /\|\s*:?-{3,}:?\s*\|/.test(trimmed);

      if (!looksLikeCompactTable) {
        return line;
      }

      return line.replace(/\|\s+\|/g, "|\n|");
    })
    .join("\n");
}

function normalizeAccidentalIndentedMarkdown(content: string) {
  let insideFence = false;

  return content
    .split("\n")
    .map((line) => {
      if (/^\s*```/.test(line)) {
        insideFence = !insideFence;
        return line;
      }
      if (insideFence) {
        return line;
      }

      const looksLikeMarkdownText =
        /^\s{4,}(#{1,6}\s|\*\*|[-*+]\s|\d+\.\s|>\s|\|)/.test(line);
      return looksLikeMarkdownText ? line.trimStart() : line;
    })
    .join("\n");
}
