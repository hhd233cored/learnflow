"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, MessageCircle, Send, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkMath from "remark-math";
import { api } from "@/lib/api";
import type { ChatMessage, GoalDetail, StudyPlan } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

type ChatDrawerProps = {
  goal: GoalDetail | null;
  selectedPlan: StudyPlan | null;
};

const initialMessages: ChatMessage[] = [
  {
    role: "assistant",
    content: "你好，我是你的 AI 学习助手。可以问我知识点、当前任务，或让我结合你的计划解释教材内容。"
  }
];

export function ChatDrawer({ goal, selectedPlan }: ChatDrawerProps) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollAreaRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const scrollArea = scrollAreaRef.current;
    if (!scrollArea) {
      return;
    }

    // 流式输出时 chunk 很密集，smooth 动画会互相打断，表现成滚动抽搐。
    // 因此 streaming 期间使用同步贴底；普通消息变化时再保留平滑滚动。
    scrollArea.scrollTo({
      top: scrollArea.scrollHeight,
      behavior: streaming ? "auto" : "smooth"
    });
  }, [messages, open, streaming]);

  async function sendMessage() {
    const content = input.trim();
    if (!content || streaming) {
      return;
    }

    const nextMessages: ChatMessage[] = [
      ...messages,
      { role: "user", content },
      { role: "assistant", content: "" }
    ];
    setMessages(nextMessages);
    setInput("");
    setStreaming(true);

    try {
      const reader = await api.streamChat({
        messages: nextMessages
          .filter((message) => message.content.trim())
          .slice(-12),
        goal_id: goal?.id,
        plan_id: selectedPlan?.id
      });
      const decoder = new TextDecoder("utf-8");

      // 逐块读取后端文本流，把内容追加到最后一条 assistant 消息上。
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        const chunk = decoder.decode(value, { stream: true });
        if (!chunk) {
          continue;
        }
        setMessages((current) => {
          const updated = [...current];
          const last = updated[updated.length - 1];
          updated[updated.length - 1] = {
            ...last,
            content: `${last.content}${chunk}`
          };
          return updated;
        });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "聊天请求失败";
      setMessages((current) => {
        const updated = [...current];
        updated[updated.length - 1] = {
          role: "assistant",
          content: `聊天暂时不可用：${message}`
        };
        return updated;
      });
    } finally {
      setStreaming(false);
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  function renderMessage(message: ChatMessage) {
    if (!message.content) {
      return (
        <span className="inline-flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          思考中
        </span>
      );
    }

    return <MarkdownMessage content={message.content} />;
  }

  return (
    <>
      <Button
        className="fixed bottom-5 right-5 z-40 shadow-lg"
        onClick={() => setOpen(true)}
        title="打开 AI 助手"
      >
        <MessageCircle className="h-4 w-4" aria-hidden="true" />
        AI 助手
      </Button>

      <div
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-full max-w-[440px] translate-x-full flex-col border-l bg-card shadow-2xl transition-transform duration-200 sm:w-[440px]",
          open && "translate-x-0"
        )}
      >
        <div className="flex h-14 items-center justify-between border-b px-4">
          <div>
            <h2 className="text-sm font-semibold">AI 学习助手</h2>
            <p className="text-xs text-muted-foreground">
              {selectedPlan
                ? `当前上下文：Day ${selectedPlan.day_index}`
                : goal
                  ? "当前上下文：学习目标"
                  : "当前上下文：通用问答"}
            </p>
          </div>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => setOpen(false)}
            title="关闭"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>

        <div
          className="flex-1 space-y-4 overflow-y-auto px-4 py-4"
          ref={scrollAreaRef}
        >
          {messages.map((message, index) => (
            <div
              className={cn(
                "flex",
                message.role === "user" ? "justify-end" : "justify-start"
              )}
              key={`${message.role}-${index}`}
            >
              <div
                className={cn(
                  "max-w-[86%] rounded-md px-3 py-2 text-sm leading-6",
                  message.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "border bg-background text-foreground"
                )}
              >
                {renderMessage(message)}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <div className="border-t p-4">
          <div className="flex gap-2">
            <Textarea
              className="min-h-11 flex-1 resize-none"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入问题..."
              disabled={streaming}
            />
            <Button
              size="icon"
              onClick={() => void sendMessage()}
              disabled={!input.trim() || streaming}
              title="发送"
            >
              {streaming ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Send className="h-4 w-4" aria-hidden="true" />
              )}
            </Button>
          </div>
        </div>
      </div>

      {open ? (
        <button
          className="fixed inset-0 z-40 bg-black/20 sm:hidden"
          onClick={() => setOpen(false)}
          aria-label="关闭聊天面板"
        />
      ) : null}
    </>
  );
}

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          p: ({ children }) => <p>{children}</p>,
          code: ({ className, children, ...props }) => {
            const isBlock = /language-/.test(className ?? "");
            if (!isBlock) {
              return (
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.92em]" {...props}>
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
        {normalizeMathMarkdown(content)}
      </ReactMarkdown>
    </div>
  );
}

function normalizeMathMarkdown(content: string) {
  return content
    .replace(/\\\[((?:.|\n)*?)\\\]/g, (_, formula: string) => `\n$$\n${formula.trim()}\n$$\n`)
    .replace(/\\\(((?:.|\n)*?)\\\)/g, (_, formula: string) => `$${formula.trim()}$`);
}
