"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  ImageIcon,
  Loader2,
  MessageCircle,
  Plus,
  RefreshCcw,
  Search,
  Send,
  Settings,
  SlidersHorizontal,
  Trash2,
  Upload,
  X
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { api } from "@/lib/api";
import type {
  Adjustment,
  ChatMessage,
  CourseMaterial,
  GoalDetail,
  GoalSummary,
  KnowledgeSearchHit,
  ReadingContext,
  Review,
  StudyPlan,
  StudyTask
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import {
  createChatSession,
  deleteChatSession,
  getActiveChatSessionId,
  getChatMessages,
  listChatSessions,
  saveChatMessages,
  setActiveChatSessionId,
  updateChatSession
} from "@/lib/chat-sessions";
import type { ChatSession, ChatSessionContext } from "@/lib/chat-sessions";
import { cn } from "@/lib/utils";

export type DrawerPanel = "chat" | "knowledge" | "review" | "settings";

type AppTheme = "default" | "dark" | "mint";
type BackgroundImageSource = "none" | "url" | "local";

type AppSettings = {
  theme: AppTheme;
  panelOpacity: number;
  backgroundOpacity: number;
  backgroundOverlay: number;
  backgroundImage: string;
  backgroundImageSource: BackgroundImageSource;
};

type ChatDrawerProps = {
  adjustment: Adjustment | null;
  currentMaterials: CourseMaterial[];
  feedback: string;
  goal: GoalDetail | null;
  goalSummaries: GoalSummary[];
  isBusy: boolean;
  loadingStep: string | null;
  requestedPanel?: DrawerPanel | null;
  readingContext?: ReadingContext | null;
  review: Review | null;
  selectedPlan: StudyPlan | null;
  selectedTasks: StudyTask[];
  onAdjustPlan: () => Promise<void>;
  onCreateReview: () => Promise<void>;
  onFeedbackChange: (value: string) => void;
  onRequestedPanelHandled?: () => void;
  onWorkspaceChange?: () => Promise<void>;
};

const initialMessages: ChatMessage[] = [
  {
    role: "assistant",
    content:
      "Ciallo～(∠・ω< )⌒★，我是 learnflow Agent。可以问我知识点、当前任务，也可以让我调用复盘、调整计划或知识库工具。"
  }
];

const SETTINGS_STORAGE_KEY = "studyagent:appSettings";
const BACKGROUND_IMAGE_DB_NAME = "studyagent-assets";
const BACKGROUND_IMAGE_STORE_NAME = "settings";
const BACKGROUND_IMAGE_KEY = "background-image";
const defaultAppSettings: AppSettings = {
  theme: "default",
  panelOpacity: 100,
  backgroundOpacity: 100,
  backgroundOverlay: 60,
  backgroundImage: "",
  backgroundImageSource: "none"
};

export function ChatDrawer({
  adjustment,
  currentMaterials,
  feedback,
  goal,
  goalSummaries,
  isBusy,
  loadingStep,
  requestedPanel,
  readingContext,
  review,
  selectedPlan,
  selectedTasks,
  onAdjustPlan,
  onCreateReview,
  onFeedbackChange,
  onRequestedPanelHandled,
  onWorkspaceChange
}: ChatDrawerProps) {
  const [activePanel, setActivePanel] = useState<DrawerPanel | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [chatSessionsReady, setChatSessionsReady] = useState(false);
  const [activeSessionLoaded, setActiveSessionLoaded] = useState(false);
  const [chatSessionError, setChatSessionError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [knowledgeGoalId, setKnowledgeGoalId] = useState<number | null>(
    goal?.id ?? null
  );
  const [knowledgeGoal, setKnowledgeGoal] = useState<GoalDetail | null>(goal);
  const [knowledgePlanId, setKnowledgePlanId] = useState<number | null>(
    selectedPlan?.id ?? null
  );
  const [knowledgeMaterials, setKnowledgeMaterials] = useState<CourseMaterial[]>([]);
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  const [knowledgeHits, setKnowledgeHits] = useState<KnowledgeSearchHit[]>([]);
  const [selectedMaterialId, setSelectedMaterialId] = useState<number | null>(null);
  const [manualSourceName, setManualSourceName] = useState("手动补充");
  const [manualContent, setManualContent] = useState("");
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);
  const [searchingKnowledge, setSearchingKnowledge] = useState(false);
  const [uploadingKnowledge, setUploadingKnowledge] = useState(false);
  const [insertingKnowledge, setInsertingKnowledge] = useState(false);
  const [deletingKnowledgeMaterialId, setDeletingKnowledgeMaterialId] = useState<number | null>(null);
  const [loadingKnowledge, setLoadingKnowledge] = useState(false);
  const [appSettings, setAppSettings] = useState<AppSettings>(defaultAppSettings);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const scrollAreaRef = useRef<HTMLDivElement | null>(null);

  const open = activePanel !== null;
  const knowledgeGoals = useMemo(
    () => goalOptions(goalSummaries, goal),
    [goal, goalSummaries]
  );
  const knowledgePlans = useMemo(
    () => [...(knowledgeGoal?.plans ?? [])].sort((a, b) => a.day_index - b.day_index),
    [knowledgeGoal]
  );
  const activeKnowledgePlan = useMemo(
    () => knowledgePlans.find((plan) => plan.id === knowledgePlanId) ?? null,
    [knowledgePlanId, knowledgePlans]
  );
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
  const chatContext = useMemo(
    () => buildChatSessionContext(goal, selectedPlan, readingContext),
    [goal, readingContext, selectedPlan]
  );

  useEffect(() => {
    if (!requestedPanel) {
      return;
    }
    setActivePanel(requestedPanel);
    onRequestedPanelHandled?.();
  }, [onRequestedPanelHandled, requestedPanel]);

  useEffect(() => {
    let cancelled = false;

    async function loadInitialChatSession() {
      try {
        const sessions = listChatSessions();
        const storedActiveId = getActiveChatSessionId();
        const activeSession =
          sessions.find((session) => session.id === storedActiveId) ?? sessions[0];
        const session = activeSession ?? createChatSession(chatContext);
        const storedMessages = await getChatMessages(session.id);

        if (cancelled) {
          return;
        }
        setChatSessions(listChatSessions());
        setActiveSessionId(session.id);
        setMessages(storedMessages.length > 0 ? storedMessages : initialMessages);
        setActiveSessionLoaded(true);
      } catch (error) {
        if (cancelled) {
          return;
        }
        setChatSessionError(`会话记录读取失败：${errorMessage(error)}`);
        setMessages(initialMessages);
        setActiveSessionLoaded(true);
      } finally {
        if (!cancelled) {
          setChatSessionsReady(true);
        }
      }
    }

    void loadInitialChatSession();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!chatSessionsReady || !activeSessionLoaded || !activeSessionId) {
      return;
    }

    void saveChatMessages(activeSessionId, messages).catch((error) => {
      setChatSessionError(`会话记录保存失败：${errorMessage(error)}`);
    });
  }, [activeSessionId, activeSessionLoaded, chatSessionsReady, messages]);

  useEffect(() => {
    let cancelled = false;

    async function loadSettings() {
      const stored = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
      if (!stored) {
        setSettingsLoaded(true);
        return;
      }

      try {
        const parsed = JSON.parse(stored) as Partial<AppSettings>;
        const storedBackground =
          typeof parsed.backgroundImage === "string" ? parsed.backgroundImage : "";
        const storedSource = isBackgroundImageSource(parsed.backgroundImageSource)
          ? parsed.backgroundImageSource
          : deriveBackgroundImageSource(storedBackground);

        const nextSettings: AppSettings = {
          theme: isAppTheme(parsed.theme) ? parsed.theme : defaultAppSettings.theme,
          panelOpacity:
            typeof parsed.panelOpacity === "number"
              ? clampPanelOpacity(parsed.panelOpacity)
              : defaultAppSettings.panelOpacity,
          backgroundOpacity:
            typeof parsed.backgroundOpacity === "number"
              ? clampOpacity(parsed.backgroundOpacity)
              : defaultAppSettings.backgroundOpacity,
          backgroundOverlay:
            typeof parsed.backgroundOverlay === "number"
              ? clampOpacity(parsed.backgroundOverlay)
              : defaultAppSettings.backgroundOverlay,
          backgroundImage: storedSource === "url" ? storedBackground : "",
          backgroundImageSource: storedSource
        };

        // 兼容旧版本：如果曾经把 data URL 直接写进 localStorage，这里会迁移到 IndexedDB。
        if (storedBackground.startsWith("data:")) {
          await saveBackgroundImageToDb(storedBackground);
          nextSettings.backgroundImage = storedBackground;
          nextSettings.backgroundImageSource = "local";
        } else if (storedSource === "local") {
          nextSettings.backgroundImage = (await loadBackgroundImageFromDb()) ?? "";
          if (!nextSettings.backgroundImage) {
            nextSettings.backgroundImageSource = "none";
          }
        }

        if (!cancelled) {
          setAppSettings(nextSettings);
        }
      } catch (error) {
        window.localStorage.removeItem(SETTINGS_STORAGE_KEY);
        if (!cancelled) {
          setSettingsError(`读取本地设置失败，已恢复默认值：${errorMessage(error)}`);
        }
      } finally {
        if (!cancelled) {
          setSettingsLoaded(true);
        }
      }
    }

    void loadSettings();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (appSettings.theme === "default") {
      root.removeAttribute("data-theme");
    } else {
      root.dataset.theme = appSettings.theme;
    }
    root.style.setProperty("--panel-alpha", String(appSettings.panelOpacity / 100));
    root.style.setProperty(
      "--background-image-alpha",
      String(appSettings.backgroundOpacity / 100)
    );
    root.style.setProperty(
      "--background-overlay-alpha",
      String(appSettings.backgroundOverlay / 100)
    );
    root.style.setProperty(
      "--app-background-image",
      appSettings.backgroundImage ? cssBackgroundUrl(appSettings.backgroundImage) : "none"
    );
    if (!settingsLoaded) {
      return;
    }
    try {
      window.localStorage.setItem(
        SETTINGS_STORAGE_KEY,
        JSON.stringify(settingsForLocalStorage(appSettings))
      );
    } catch (error) {
      setSettingsError(`保存设置失败：${errorMessage(error)}`);
    }
  }, [appSettings, settingsLoaded]);

  useEffect(() => {
    if (goal) {
      setKnowledgeGoalId(goal.id);
      return;
    }
    setKnowledgeGoalId((current) => current ?? knowledgeGoals[0]?.id ?? null);
  }, [goal?.id, knowledgeGoals]);

  useEffect(() => {
    if (!knowledgeGoalId) {
      setKnowledgeGoal(null);
      setKnowledgeMaterials([]);
      return;
    }

    let cancelled = false;
    setLoadingKnowledge(true);
    setKnowledgeError(null);

    Promise.all([api.getGoal(knowledgeGoalId), api.listMaterials(knowledgeGoalId)])
      .then(([detail, materials]) => {
        if (cancelled) {
          return;
        }
        setKnowledgeGoal(detail);
        setKnowledgeMaterials(materials);
        setSelectedMaterialId((current) =>
          current && materials.some((item) => item.id === current) ? current : null
        );

        const nextPlans = [...detail.plans].sort(
          (left, right) => left.day_index - right.day_index
        );
        setKnowledgePlanId((current) => {
          if (current && nextPlans.some((plan) => plan.id === current)) {
            return current;
          }
          if (goal?.id === detail.id && selectedPlan) {
            return selectedPlan.id;
          }
          return null;
        });
      })
      .catch((err) => {
        if (!cancelled) {
          setKnowledgeError(err instanceof Error ? err.message : "知识库加载失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingKnowledge(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [goal?.id, knowledgeGoalId, selectedPlan]);

  useEffect(() => {
    if (goal?.id === knowledgeGoalId) {
      setKnowledgeMaterials(currentMaterials);
    }
  }, [currentMaterials, goal?.id, knowledgeGoalId]);

  useEffect(() => {
    if (activePanel !== "chat") {
      return;
    }
    const scrollArea = scrollAreaRef.current;
    if (!scrollArea) {
      return;
    }

    // 流式输出时不使用 smooth，避免连续 chunk 造成滚动抖动。
    scrollArea.scrollTo({
      top: scrollArea.scrollHeight,
      behavior: streaming ? "auto" : "smooth"
    });
  }, [activePanel, messages, streaming]);

  function openPanel(panel: DrawerPanel) {
    setActivePanel((current) => (current === panel ? null : panel));
  }

  function refreshChatSessions() {
    setChatSessions(listChatSessions());
  }

  function ensureActiveChatSessionForMessage(content: string) {
    let sessionId = activeSessionId;
    if (!sessionId) {
      const session = createChatSession(chatContext, sessionTitleFromMessage(content));
      sessionId = session.id;
      setActiveSessionId(session.id);
      setActiveSessionLoaded(true);
    } else {
      const currentSession = chatSessions.find((session) => session.id === sessionId);
      updateChatSession(sessionId, {
        context: chatContext,
        title:
          !currentSession?.title || currentSession.title === "新会话"
            ? sessionTitleFromMessage(content)
            : currentSession.title
      });
    }
    setActiveChatSessionId(sessionId);
    refreshChatSessions();
  }

  async function createNewChatSession() {
    try {
      const session = createChatSession(chatContext);
      setActiveSessionLoaded(false);
      setActiveSessionId(session.id);
      setMessages(initialMessages);
      await saveChatMessages(session.id, initialMessages);
      setActiveSessionLoaded(true);
      setChatSessionError(null);
      refreshChatSessions();
    } catch (error) {
      setChatSessionError(`新建会话失败：${errorMessage(error)}`);
    }
  }

  async function selectChatSession(sessionId: string) {
    if (!sessionId || sessionId === activeSessionId) {
      return;
    }
    setActiveSessionLoaded(false);
    setActiveSessionId(sessionId);
    setActiveChatSessionId(sessionId);
    try {
      const storedMessages = await getChatMessages(sessionId);
      setMessages(storedMessages.length > 0 ? storedMessages : initialMessages);
      setChatSessionError(null);
    } catch (error) {
      setMessages(initialMessages);
      setChatSessionError(`会话切换失败：${errorMessage(error)}`);
    } finally {
      setActiveSessionLoaded(true);
      refreshChatSessions();
    }
  }

  async function removeActiveChatSession() {
    if (!activeSessionId || streaming) {
      return;
    }

    try {
      await deleteChatSession(activeSessionId);
      const remainingSessions = listChatSessions();
      const nextSession = remainingSessions[0] ?? createChatSession(chatContext);
      const storedMessages = await getChatMessages(nextSession.id);
      setActiveSessionLoaded(false);
      setActiveSessionId(nextSession.id);
      setActiveChatSessionId(nextSession.id);
      setMessages(storedMessages.length > 0 ? storedMessages : initialMessages);
      setActiveSessionLoaded(true);
      setChatSessionError(null);
      refreshChatSessions();
    } catch (error) {
      setChatSessionError(`删除会话失败：${errorMessage(error)}`);
    }
  }

  function updateAppSettings(patch: Partial<AppSettings>) {
    setAppSettings((current) => ({
      ...current,
      ...patch,
      backgroundImageSource:
        patch.backgroundImageSource ??
        (typeof patch.backgroundImage === "string"
          ? deriveBackgroundImageSource(patch.backgroundImage)
          : current.backgroundImageSource),
      panelOpacity:
        typeof patch.panelOpacity === "number"
          ? clampPanelOpacity(patch.panelOpacity)
          : current.panelOpacity,
      backgroundOpacity:
        typeof patch.backgroundOpacity === "number"
          ? clampOpacity(patch.backgroundOpacity)
          : current.backgroundOpacity,
      backgroundOverlay:
        typeof patch.backgroundOverlay === "number"
          ? clampOpacity(patch.backgroundOverlay)
          : current.backgroundOverlay
    }));
  }

  async function resetAppSettings() {
    await deleteBackgroundImageFromDb();
    setSettingsError(null);
    setAppSettings(defaultAppSettings);
  }

  async function handleBackgroundFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      setSettingsError("请选择 JPG、PNG、WebP 等图片文件作为背景。");
      return;
    }

    try {
      const dataUrl = await readFileAsDataUrl(file);
      await saveBackgroundImageToDb(dataUrl);
      setSettingsError(null);
      updateAppSettings({
        backgroundImage: dataUrl,
        backgroundImageSource: "local"
      });
    } catch (error) {
      setSettingsError(`背景图保存失败：${errorMessage(error)}`);
    }
  }

  function handleKnowledgeGoalChange(goalId: number | null) {
    setKnowledgeGoalId(goalId);
    setKnowledgePlanId(null);
    setSelectedMaterialId(null);
    setKnowledgeHits([]);
    setKnowledgeError(null);
  }

  async function refreshKnowledgeMaterials(goalId = knowledgeGoalId) {
    if (!goalId) {
      return;
    }
    const materials = await api.listMaterials(goalId);
    setKnowledgeMaterials(materials);
    if (goal?.id === goalId) {
      await onWorkspaceChange?.();
    }
  }

  async function deleteKnowledgeMaterial(materialId: number) {
    if (!knowledgeGoalId || !window.confirm("删除该素材及其 OCR 缓存和知识库片段？")) {
      return;
    }
    setDeletingKnowledgeMaterialId(materialId);
    setKnowledgeError(null);
    try {
      await api.deleteMaterial(materialId);
      setSelectedMaterialId((current) => (current === materialId ? null : current));
      setKnowledgeHits([]);
      await refreshKnowledgeMaterials(knowledgeGoalId);
    } catch (error) {
      setKnowledgeError(`素材删除失败：${errorMessage(error)}`);
    } finally {
      setDeletingKnowledgeMaterialId((current) =>
        current === materialId ? null : current
      );
    }
  }

  async function sendMessage() {
    const content = input.trim();
    if (!content || streaming) {
      return;
    }

    const mayMutateWorkspace = /复盘|调整|加入知识库|写入知识库|补充到知识库|记到知识库/.test(
      content
    );
    ensureActiveChatSessionForMessage(content);

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
        plan_id: selectedPlan?.id,
        reading_context: readingContext ?? null
      });
      const decoder = new TextDecoder("utf-8");

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

      if (mayMutateWorkspace) {
        await onWorkspaceChange?.();
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

  async function searchKnowledge() {
    if (!knowledgeGoalId || !knowledgeQuery.trim()) {
      return;
    }

    setSearchingKnowledge(true);
    setKnowledgeError(null);
    try {
      const result = await api.searchKnowledge(
        knowledgeGoalId,
        knowledgeQuery.trim(),
        5,
        knowledgeFilters(activeKnowledgePlan, selectedMaterialId)
      );
      setKnowledgeHits(result.hits);
    } catch (err) {
      setKnowledgeError(err instanceof Error ? err.message : "知识库检索失败");
    } finally {
      setSearchingKnowledge(false);
    }
  }

  async function uploadKnowledgeFile(event: React.ChangeEvent<HTMLInputElement>) {
    if (!knowledgeGoalId || !event.target.files?.[0]) {
      return;
    }
    const file = event.target.files[0];
    setUploadingKnowledge(true);
    setKnowledgeError(null);
    try {
      await api.uploadMaterial(
        knowledgeGoalId,
        file,
        knowledgeFilters(activeKnowledgePlan, null)
      );
      await refreshKnowledgeMaterials(knowledgeGoalId);
    } catch (err) {
      setKnowledgeError(err instanceof Error ? err.message : "资料上传失败");
    } finally {
      event.target.value = "";
      setUploadingKnowledge(false);
    }
  }

  async function insertKnowledgeSnippet() {
    if (!knowledgeGoalId || !manualContent.trim()) {
      return;
    }
    setInsertingKnowledge(true);
    setKnowledgeError(null);
    try {
      await api.createKnowledgeSnippet(knowledgeGoalId, {
        content: manualContent.trim(),
        source_name: manualSourceName.trim() || "手动补充",
        ...knowledgeFilters(activeKnowledgePlan, null)
      });
      setManualContent("");
      await refreshKnowledgeMaterials(knowledgeGoalId);
    } catch (err) {
      setKnowledgeError(err instanceof Error ? err.message : "知识片段写入失败");
    } finally {
      setInsertingKnowledge(false);
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
      <aside className="fixed inset-y-0 right-0 z-50 hidden w-14 flex-col items-center gap-2 border-l bg-card px-2 py-4 shadow-lg md:flex">
        <ActivityButton
          active={activePanel === "chat"}
          label="AI 聊天"
          onClick={() => openPanel("chat")}
        >
          <MessageCircle className="h-5 w-5" aria-hidden="true" />
        </ActivityButton>
        <ActivityButton
          active={activePanel === "knowledge"}
          label="知识库"
          onClick={() => openPanel("knowledge")}
        >
          <BookOpen className="h-5 w-5" aria-hidden="true" />
        </ActivityButton>
        <ActivityButton
          active={activePanel === "review"}
          label="复盘调整"
          onClick={() => openPanel("review")}
        >
          <RefreshCcw className="h-5 w-5" aria-hidden="true" />
        </ActivityButton>
        <div className="mt-auto">
          <ActivityButton
            active={activePanel === "settings"}
            label="界面设置"
            onClick={() => openPanel("settings")}
          >
            <Settings className="h-5 w-5" aria-hidden="true" />
          </ActivityButton>
        </div>
      </aside>

      <div className="fixed bottom-5 right-5 z-40 flex gap-2 md:hidden">
        <Button onClick={() => openPanel("chat")} title="AI 聊天">
          <MessageCircle className="h-4 w-4" aria-hidden="true" />
          AI
        </Button>
        <Button onClick={() => openPanel("knowledge")} title="知识库">
          <BookOpen className="h-4 w-4" aria-hidden="true" />
          RAG
        </Button>
        <Button onClick={() => openPanel("review")} title="复盘调整">
          <RefreshCcw className="h-4 w-4" aria-hidden="true" />
          复盘
        </Button>
        <Button onClick={() => openPanel("settings")} title="界面设置">
          <Settings className="h-4 w-4" aria-hidden="true" />
          设置
        </Button>
      </div>

      <div
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-full max-w-[660px] translate-x-full flex-col border-l bg-card shadow-2xl transition-transform duration-200 md:right-14 md:z-40 md:w-[660px] md:max-w-none",
          open && "translate-x-0"
        )}
      >
        <div className="flex h-14 items-center justify-between border-b px-4">
          <div>
            <h2 className="text-sm font-semibold">{panelTitle(activePanel)}</h2>
            <p className="text-xs text-muted-foreground">
              {panelDescription(activePanel, selectedPlan)}
            </p>
          </div>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => setActivePanel(null)}
            title="关闭"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>

        {activePanel === "knowledge" ? (
          <KnowledgePanel
            activePlan={activeKnowledgePlan}
            error={knowledgeError}
            goalId={knowledgeGoalId}
            goals={knowledgeGoals}
            hits={knowledgeHits}
            inserting={insertingKnowledge}
            loading={loadingKnowledge}
            manualContent={manualContent}
            manualSourceName={manualSourceName}
            materials={knowledgeMaterials}
            onGoalChange={handleKnowledgeGoalChange}
            onInsert={() => void insertKnowledgeSnippet()}
            onDeleteMaterial={(materialId) => void deleteKnowledgeMaterial(materialId)}
            onManualContentChange={setManualContent}
            onManualSourceNameChange={setManualSourceName}
            onMaterialChange={setSelectedMaterialId}
            onPlanChange={setKnowledgePlanId}
            onQueryChange={setKnowledgeQuery}
            onSearch={() => void searchKnowledge()}
            onUpload={uploadKnowledgeFile}
            plans={knowledgePlans}
            query={knowledgeQuery}
            searching={searchingKnowledge}
            selectedMaterialId={selectedMaterialId}
            deletingMaterialId={deletingKnowledgeMaterialId}
            uploading={uploadingKnowledge}
          />
        ) : activePanel === "settings" ? (
          <SettingsPanel
            error={settingsError}
            settings={appSettings}
            onBackgroundFile={handleBackgroundFile}
            onReset={resetAppSettings}
            onSettingsChange={updateAppSettings}
          />
        ) : activePanel === "review" ? (
          <ReviewPanel
            adjustment={adjustment}
            completionRate={completionRate}
            feedback={feedback}
            isBusy={isBusy}
            loadingStep={loadingStep}
            onAdjustPlan={onAdjustPlan}
            onCreateReview={onCreateReview}
            onFeedbackChange={onFeedbackChange}
            review={review}
            selectedPlan={selectedPlan}
            selectedTasks={selectedTasks}
          />
        ) : (
          <ChatPanel
            activeSessionId={activeSessionId}
            chatSessionError={chatSessionError}
            chatSessions={chatSessions}
            input={input}
            messages={messages}
            onCreateSession={() => void createNewChatSession()}
            onDeleteSession={() => void removeActiveChatSession()}
            onInputChange={setInput}
            onKeyDown={handleKeyDown}
            onSend={() => void sendMessage()}
            onSelectSession={(sessionId) => void selectChatSession(sessionId)}
            renderMessage={renderMessage}
            scrollAreaRef={scrollAreaRef}
            streaming={streaming}
          />
        )}
      </div>

      {open ? (
        <button
          className="fixed inset-0 z-40 bg-black/20 sm:hidden"
          onClick={() => setActivePanel(null)}
          aria-label="关闭侧边栏"
        />
      ) : null}
    </>
  );
}

function ActivityButton({
  active,
  children,
  label,
  onClick
}: {
  active: boolean;
  children: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={cn(
        "flex h-11 w-11 items-center justify-center rounded-md hover:bg-muted",
        active && "bg-teal-50 text-primary"
      )}
      onClick={onClick}
      title={label}
    >
      {children}
    </button>
  );
}

function SettingsPanel({
  error,
  settings,
  onBackgroundFile,
  onReset,
  onSettingsChange
}: {
  error: string | null;
  settings: AppSettings;
  onBackgroundFile: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onReset: () => void;
  onSettingsChange: (patch: Partial<AppSettings>) => void;
}) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div className="space-y-4">
        <div className="rounded-md border bg-background p-4">
          <div className="mb-3 flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-primary" aria-hidden="true" />
            <h3 className="text-sm font-semibold">主题</h3>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: "默认", value: "default" as const },
              { label: "深色", value: "dark" as const },
              { label: "青绿", value: "mint" as const }
            ].map((item) => (
              <button
                className={cn(
                  "h-10 rounded-md border text-sm transition-colors hover:bg-muted",
                  settings.theme === item.value && "border-primary bg-teal-50 text-primary"
                )}
                key={item.value}
                type="button"
                onClick={() => onSettingsChange({ theme: item.value })}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-md border bg-background p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 text-primary" aria-hidden="true" />
              <h3 className="text-sm font-semibold">Panel 透明度</h3>
            </div>
            <span className="text-sm font-medium">{settings.panelOpacity}%</span>
          </div>
          <input
            aria-label="Panel 透明度"
            className="w-full accent-primary"
            max={100}
            min={0}
            step={5}
            type="range"
            value={settings.panelOpacity}
            onChange={(event) =>
              onSettingsChange({ panelOpacity: Number(event.target.value) })
            }
          />
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            透明度会作用于主页面卡片、任务卡片和右侧面板。
          </p>
        </div>

        <div className="rounded-md border bg-background p-4">
          <div className="mb-3 flex items-center gap-2">
            <ImageIcon className="h-4 w-4 text-primary" aria-hidden="true" />
            <h3 className="text-sm font-semibold">背景图片</h3>
          </div>
          <div className="space-y-3">
            {error ? (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                {error}
              </div>
            ) : null}
            <Input
              value={settings.backgroundImageSource === "url" ? settings.backgroundImage : ""}
              onChange={(event) =>
                onSettingsChange({
                  backgroundImage: event.target.value.trim(),
                  backgroundImageSource: event.target.value.trim() ? "url" : "none"
                })
              }
              placeholder="输入图片 URL，或上传本地图片"
            />
            <Input
              accept="image/*"
              type="file"
              onChange={onBackgroundFile}
            />
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="text-muted-foreground">背景图透明度</span>
                <span className="font-medium">{settings.backgroundOpacity}%</span>
              </div>
              <input
                aria-label="背景图透明度"
                className="w-full accent-primary"
                max={100}
                min={0}
                step={5}
                type="range"
                value={settings.backgroundOpacity}
                onChange={(event) =>
                  onSettingsChange({ backgroundOpacity: Number(event.target.value) })
                }
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="text-muted-foreground">背景遮罩强度</span>
                <span className="font-medium">{settings.backgroundOverlay}%</span>
              </div>
              <input
                aria-label="背景遮罩强度"
                className="w-full accent-primary"
                max={100}
                min={0}
                step={5}
                type="range"
                value={settings.backgroundOverlay}
                onChange={(event) =>
                  onSettingsChange({ backgroundOverlay: Number(event.target.value) })
                }
              />
              <p className="text-xs leading-5 text-muted-foreground">
                调低后背景更清晰；调高后内容区域更柔和、更容易阅读。
              </p>
            </div>
            {settings.backgroundImage ? (
              <div
                className="h-28 rounded-md border bg-cover bg-center"
                style={{
                  backgroundImage: `linear-gradient(rgba(255,255,255,${
                    1 - settings.backgroundOpacity / 100
                  }), rgba(255,255,255,${
                    1 - settings.backgroundOpacity / 100
                  })), ${cssBackgroundUrl(settings.backgroundImage)}`
                }}
              />
            ) : (
              <div className="flex h-28 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
                暂未设置背景图片
              </div>
            )}
          </div>
        </div>

        <Button variant="outline" className="w-full" onClick={onReset}>
          恢复默认设置
        </Button>
      </div>
    </div>
  );
}

function ChatPanel({
  activeSessionId,
  chatSessionError,
  chatSessions,
  input,
  messages,
  onCreateSession,
  onDeleteSession,
  onInputChange,
  onKeyDown,
  onSend,
  onSelectSession,
  renderMessage,
  scrollAreaRef,
  streaming
}: {
  activeSessionId: string | null;
  chatSessionError: string | null;
  chatSessions: ChatSession[];
  input: string;
  messages: ChatMessage[];
  onCreateSession: () => void;
  onDeleteSession: () => void;
  onInputChange: (value: string) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSend: () => void;
  onSelectSession: (sessionId: string) => void;
  renderMessage: (message: ChatMessage) => React.ReactNode;
  scrollAreaRef: React.RefObject<HTMLDivElement | null>;
  streaming: boolean;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b p-3">
        <div className="flex items-center gap-2">
          <select
            className="h-9 min-w-0 flex-1 rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={activeSessionId ?? ""}
            onChange={(event) => onSelectSession(event.target.value)}
            disabled={streaming}
            title="切换会话"
          >
            {chatSessions.length > 0 ? (
              chatSessions.map((session) => (
                <option key={session.id} value={session.id}>
                  {session.title} · {sessionContextLabel(session)}
                </option>
              ))
            ) : (
              <option value="">新会话</option>
            )}
          </select>
          <Button
            size="icon"
            variant="outline"
            onClick={onCreateSession}
            disabled={streaming}
            title="新建会话"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button
            size="icon"
            variant="outline"
            onClick={onDeleteSession}
            disabled={!activeSessionId || streaming}
            title="删除当前会话"
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
        {chatSessionError ? (
          <p className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800">
            {chatSessionError}
          </p>
        ) : null}
      </div>
      <div
        className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4"
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
                "max-w-[92%] rounded-md px-3 py-2 text-sm leading-6",
                message.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "border bg-background text-foreground"
              )}
            >
              {renderMessage(message)}
            </div>
          </div>
        ))}
      </div>

      <div className="border-t p-4">
        <div className="flex gap-2">
          <Textarea
            className="min-h-11 flex-1 resize-none"
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder="输入问题，或说“帮我复盘并调整明天计划”..."
            disabled={streaming}
          />
          <Button
            size="icon"
            onClick={onSend}
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
  );
}

function KnowledgePanel({
  activePlan,
  error,
  goalId,
  goals,
  hits,
  inserting,
  deletingMaterialId,
  loading,
  manualContent,
  manualSourceName,
  materials,
  onGoalChange,
  onInsert,
  onDeleteMaterial,
  onManualContentChange,
  onManualSourceNameChange,
  onMaterialChange,
  onPlanChange,
  onQueryChange,
  onSearch,
  onUpload,
  plans,
  query,
  searching,
  selectedMaterialId,
  uploading
}: {
  activePlan: StudyPlan | null;
  error: string | null;
  goalId: number | null;
  goals: Array<{ id: number; title: string }>;
  hits: KnowledgeSearchHit[];
  inserting: boolean;
  deletingMaterialId: number | null;
  loading: boolean;
  manualContent: string;
  manualSourceName: string;
  materials: CourseMaterial[];
  onGoalChange: (goalId: number | null) => void;
  onInsert: () => void;
  onDeleteMaterial: (materialId: number) => void;
  onManualContentChange: (value: string) => void;
  onManualSourceNameChange: (value: string) => void;
  onMaterialChange: (materialId: number | null) => void;
  onPlanChange: (planId: number | null) => void;
  onQueryChange: (query: string) => void;
  onSearch: () => void;
  onUpload: (event: React.ChangeEvent<HTMLInputElement>) => void;
  plans: StudyPlan[];
  query: string;
  searching: boolean;
  selectedMaterialId: number | null;
  uploading: boolean;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-4 border-b p-4">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="knowledgeGoal">学习目标知识库</Label>
            <select
              id="knowledgeGoal"
              className="h-10 w-full rounded-md border bg-background px-3 text-sm"
              value={goalId ?? ""}
              onChange={(event) =>
                onGoalChange(event.target.value ? Number(event.target.value) : null)
              }
            >
              {goals.length > 0 ? (
                goals.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))
              ) : (
                <option value="">暂无学习目标</option>
              )}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="knowledgePlan">关联 Day</Label>
            <select
              id="knowledgePlan"
              className="h-10 w-full rounded-md border bg-background px-3 text-sm"
              value={activePlan?.id ?? ""}
              onChange={(event) =>
                onPlanChange(event.target.value ? Number(event.target.value) : null)
              }
              disabled={!goalId || plans.length === 0}
            >
              <option value="">不限定 Day</option>
              {plans.map((plan) => (
                <option key={plan.id} value={plan.id}>
                  Day {plan.day_index} · {plan.topic}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="rounded-md border bg-background p-3">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold">新增素材</h3>
              <p className="text-xs text-muted-foreground">
                文件和手动片段都会写入目标级 collection，并带上素材与 Day metadata。
              </p>
            </div>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          </div>

          <div className="grid gap-3 md:grid-cols-[1fr_auto]">
            <Input
              type="file"
              accept=".pdf,.docx,.pptx,.txt,.md"
              disabled={!goalId || uploading}
              onChange={onUpload}
            />
            <div className="flex h-10 items-center gap-2 rounded-md border bg-muted px-3 text-xs text-muted-foreground">
              {uploading ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Upload className="h-4 w-4" aria-hidden="true" />
              )}
              选择文件后自动上传
            </div>
          </div>

          <div className="mt-3 grid gap-2 md:grid-cols-[180px_1fr_auto]">
            <Input
              value={manualSourceName}
              onChange={(event) => onManualSourceNameChange(event.target.value)}
              placeholder="片段来源"
              disabled={!goalId || inserting}
            />
            <Input
              value={manualContent}
              onChange={(event) => onManualContentChange(event.target.value)}
              placeholder="输入要补充进知识库的知识片段..."
              disabled={!goalId || inserting}
            />
            <Button
              variant="secondary"
              onClick={onInsert}
              disabled={!goalId || !manualContent.trim() || inserting}
            >
              {inserting ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Plus className="h-4 w-4" aria-hidden="true" />
              )}
              插入
            </Button>
          </div>
        </div>

        <div className="grid gap-2 md:grid-cols-[1fr_180px_auto]">
          <Input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            disabled={!goalId || searching}
            placeholder="输入关键词或问题..."
          />
          <select
            className="h-10 rounded-md border bg-background px-3 text-sm"
            value={selectedMaterialId ?? ""}
            onChange={(event) =>
              onMaterialChange(event.target.value ? Number(event.target.value) : null)
            }
            disabled={!goalId || materials.length === 0}
          >
            <option value="">全部素材</option>
            {materials.map((material) => (
              <option key={material.id} value={material.id}>
                {material.filename}
              </option>
            ))}
          </select>
          <Button
            size="icon"
            variant="outline"
            onClick={onSearch}
            disabled={!goalId || !query.trim() || searching}
            title="检索知识库"
          >
            {searching ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Search className="h-4 w-4" aria-hidden="true" />
            )}
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {error ? (
          <div className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {error}
          </div>
        ) : null}

        <div className="mb-4 grid gap-2 md:grid-cols-2">
          {materials.length > 0 ? (
            materials.slice(0, 6).map((material) => (
              <MaterialCard
                deleting={deletingMaterialId === material.id}
                material={material}
                key={material.id}
                onDelete={onDeleteMaterial}
              />
            ))
          ) : (
            <div className="rounded-md border border-dashed bg-background px-4 py-6 text-center text-sm text-muted-foreground md:col-span-2">
              还没有素材，上传文件或手动插入片段后即可检索。
            </div>
          )}
        </div>

        {hits.length > 0 ? (
          <div className="space-y-3">
            {hits.map((hit, index) => (
              <KnowledgeHitCard hit={hit} key={index} />
            ))}
          </div>
        ) : (
          <div className="rounded-md border border-dashed bg-background px-4 py-10 text-center text-sm text-muted-foreground">
            {goalId
              ? "选择知识库、Day 或素材后输入关键词检索。"
              : "创建学习目标后，这里可以管理对应的 RAG 知识库。"}
          </div>
        )}
      </div>
    </div>
  );
}

function ReviewPanel({
  adjustment,
  completionRate,
  feedback,
  isBusy,
  loadingStep,
  onAdjustPlan,
  onCreateReview,
  onFeedbackChange,
  review,
  selectedPlan,
  selectedTasks
}: {
  adjustment: Adjustment | null;
  completionRate: number;
  feedback: string;
  isBusy: boolean;
  loadingStep: string | null;
  onAdjustPlan: () => Promise<void>;
  onCreateReview: () => Promise<void>;
  onFeedbackChange: (value: string) => void;
  review: Review | null;
  selectedPlan: StudyPlan | null;
  selectedTasks: StudyTask[];
}) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      {selectedPlan ? (
        <div className="space-y-4">
          <div className="rounded-md border bg-background p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <Badge tone={selectedPlan.adjusted ? "amber" : "teal"}>
                  Day {selectedPlan.day_index}
                </Badge>
                <h3 className="mt-3 text-sm font-semibold">{selectedPlan.topic}</h3>
              </div>
              <span className="text-xs text-muted-foreground">
                {selectedTasks.length} 个任务
              </span>
            </div>
            <div className="mt-4 space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">任务完成度</span>
                <span className="font-medium">{completionRate}%</span>
              </div>
              <Progress value={completionRate} />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="reviewFeedback">学习反馈</Label>
            <Textarea
              id="reviewFeedback"
              value={feedback}
              onChange={(event) => onFeedbackChange(event.target.value)}
              placeholder="记录卡住的知识点、错题类型或今天的学习状态..."
            />
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <Button onClick={() => void onCreateReview()} disabled={!selectedPlan || isBusy}>
              {loadingStep === "review" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              )}
              生成复盘
            </Button>
            <Button
              variant="secondary"
              onClick={() => void onAdjustPlan()}
              disabled={!review || isBusy}
            >
              {loadingStep === "adjust" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              )}
              调整下一天
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
        </div>
      ) : (
        <div className="flex min-h-52 items-center justify-center rounded-md border border-dashed bg-background px-4 text-center text-sm text-muted-foreground">
          选择某一天计划后，可以在这里生成复盘并调整后续计划。
        </div>
      )}
    </div>
  );
}

function goalOptions(goalSummaries: GoalSummary[], goal: GoalDetail | null) {
  const options = goalSummaries.map((item) => ({
    id: item.id,
    title: `${item.title} · ${item.material_count} 份资料`
  }));

  if (goal && !options.some((item) => item.id === goal.id)) {
    options.unshift({
      id: goal.id,
      title: `${goal.title} · 当前计划`
    });
  }

  return options;
}

function knowledgeFilters(plan: StudyPlan | null, materialId: number | null) {
  return {
    ...(plan ? { plan_id: plan.id, day_index: plan.day_index } : {}),
    ...(materialId ? { material_id: materialId } : {})
  };
}

function isAppTheme(value: unknown): value is AppTheme {
  return value === "default" || value === "dark" || value === "mint";
}

function isBackgroundImageSource(value: unknown): value is BackgroundImageSource {
  return value === "none" || value === "url" || value === "local";
}

function clampPanelOpacity(value: number) {
  return clampOpacity(value);
}

function clampOpacity(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function panelTitle(panel: DrawerPanel | null) {
  if (panel === "knowledge") {
    return "课程知识库";
  }
  if (panel === "review") {
    return "复盘与调整";
  }
  if (panel === "settings") {
    return "界面设置";
  }
  return "AI 学习助手";
}

function panelDescription(panel: DrawerPanel | null, selectedPlan: StudyPlan | null) {
  if (panel === "knowledge") {
    return "上传素材、手动补充片段，并按目标、Day 或素材检索。";
  }
  if (panel === "review") {
    return selectedPlan
      ? `当前对象：Day ${selectedPlan.day_index}`
      : "选择某一天后生成复盘";
  }
  if (panel === "settings") {
    return "调整主题、透明度和背景图片。";
  }
  return selectedPlan
    ? `当前上下文：Day ${selectedPlan.day_index}`
    : "当前上下文：通用问答";
}

function MaterialCard({
  deleting,
  material,
  onDelete
}: {
  deleting: boolean;
  material: CourseMaterial;
  onDelete: (materialId: number) => void;
}) {
  return (
    <div className="rounded-md border bg-background p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <span className="line-clamp-2 font-medium">{material.filename}</span>
        <div className="flex shrink-0 items-center gap-1">
          <Badge
            tone={
              ["ready", "ocr_ready"].includes(material.parse_status)
                ? "teal"
                : material.parse_status === "failed"
                  ? "rose"
                  : "amber"
            }
          >
            {material.parse_status}
          </Badge>
          <Button
            size="icon"
            variant="ghost"
            disabled={deleting}
            title="删除素材"
            onClick={() => onDelete(material.id)}
          >
            {deleting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Trash2 className="h-4 w-4" aria-hidden="true" />
            )}
          </Button>
        </div>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {material.parse_status === "ocr_ready"
          ? `${material.chunk_count} OCR pages · ${material.file_type}`
          : `${material.chunk_count} chunks · ${material.file_type}`}
      </p>
      {material.error_message ? (
        <p className="mt-2 text-xs text-rose-700">{material.error_message}</p>
      ) : null}
    </div>
  );
}

function KnowledgeHitCard({ hit }: { hit: KnowledgeSearchHit }) {
  return (
    <div className="rounded-md border bg-background p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {metadataString(hit, "source_lang") ? (
          <Badge tone="neutral">{metadataString(hit, "source_lang")}</Badge>
        ) : null}
        {metadataString(hit, "source_type") ? (
          <Badge tone="teal">{metadataString(hit, "source_type")}</Badge>
        ) : null}
        {metadataString(hit, "source") ? (
          <span className="text-xs text-muted-foreground">
            {metadataString(hit, "source")}
          </span>
        ) : null}
      </div>
      {metadataString(hit, "summary_zh") ? (
        <p className="mb-2 text-sm leading-6">{metadataString(hit, "summary_zh")}</p>
      ) : null}
      <p className="line-clamp-5 text-sm leading-6 text-muted-foreground">
        {hit.content}
      </p>
      {metadataTerms(hit).length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {metadataTerms(hit).map((term) => (
            <Badge tone="teal" key={term}>
              {term}
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function metadataString(hit: KnowledgeSearchHit, key: string) {
  const value = hit.metadata[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function metadataTerms(hit: KnowledgeSearchHit) {
  const terms = hit.metadata.key_terms;
  if (!Array.isArray(terms)) {
    return [];
  }
  return terms
    .map((item) => {
      if (!item || typeof item !== "object") {
        return "";
      }
      const record = item as Record<string, unknown>;
      const source = typeof record.source === "string" ? record.source : "";
      const zh = typeof record.zh === "string" ? record.zh : "";
      return zh && source && zh !== source ? `${source} / ${zh}` : source || zh;
    })
    .filter(Boolean)
    .slice(0, 5);
}

function buildChatSessionContext(
  goal: GoalDetail | null,
  selectedPlan: StudyPlan | null,
  readingContext: ReadingContext | null | undefined
): ChatSessionContext {
  if (readingContext?.material_id) {
    return {
      type: "pdf",
      goalId: goal?.id,
      planId: selectedPlan?.id,
      materialId: readingContext.material_id,
      pageIndex: readingContext.page_index
    };
  }
  if (selectedPlan) {
    return {
      type: "plan",
      goalId: goal?.id,
      planId: selectedPlan.id
    };
  }
  if (goal) {
    return {
      type: "goal",
      goalId: goal.id
    };
  }
  return { type: "general" };
}

function sessionTitleFromMessage(content: string) {
  const compact = content.replace(/\s+/g, " ").trim();
  return compact.length > 20 ? `${compact.slice(0, 20)}...` : compact || "新会话";
}

function sessionContextLabel(session: ChatSession) {
  if (session.context.type === "pdf") {
    return typeof session.context.pageIndex === "number"
      ? `PDF 第 ${session.context.pageIndex + 1} 页`
      : "PDF";
  }
  if (session.context.type === "plan") {
    return session.context.planId ? `计划 #${session.context.planId}` : "计划";
  }
  if (session.context.type === "goal") {
    return session.context.goalId ? `目标 #${session.context.goalId}` : "目标";
  }
  return "通用";
}

function settingsForLocalStorage(settings: AppSettings): AppSettings {
  return {
    ...settings,
    // 本地图片可能是很长的 data URL，直接写 localStorage 容易触发浏览器配额限制。
    // 真正的图片内容放在 IndexedDB，这里只保留“使用本地图片”的小标记。
    backgroundImage: settings.backgroundImageSource === "local" ? "" : settings.backgroundImage
  };
}

function cssBackgroundUrl(value: string) {
  return `url("${value.replaceAll('"', "%22")}")`;
}

function deriveBackgroundImageSource(value: string): BackgroundImageSource {
  if (!value) {
    return "none";
  }
  return value.startsWith("data:") ? "local" : "url";
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("文件读取失败"));
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.readAsDataURL(file);
  });
}

function openBackgroundImageDb() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("当前浏览器环境不支持 IndexedDB"));
      return;
    }

    const request = indexedDB.open(BACKGROUND_IMAGE_DB_NAME, 1);
    request.onerror = () => reject(request.error ?? new Error("打开 IndexedDB 失败"));
    request.onsuccess = () => resolve(request.result);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(BACKGROUND_IMAGE_STORE_NAME)) {
        database.createObjectStore(BACKGROUND_IMAGE_STORE_NAME);
      }
    };
  });
}

async function saveBackgroundImageToDb(dataUrl: string) {
  const database = await openBackgroundImageDb();
  try {
    await runBackgroundImageTransaction(database, "readwrite", (store) => {
      store.put(dataUrl, BACKGROUND_IMAGE_KEY);
    });
  } finally {
    database.close();
  }
}

async function loadBackgroundImageFromDb() {
  const database = await openBackgroundImageDb();
  try {
    return await new Promise<string | null>((resolve, reject) => {
      const transaction = database.transaction(BACKGROUND_IMAGE_STORE_NAME, "readonly");
      const store = transaction.objectStore(BACKGROUND_IMAGE_STORE_NAME);
      const request = store.get(BACKGROUND_IMAGE_KEY);
      request.onerror = () => reject(request.error ?? new Error("读取背景图失败"));
      request.onsuccess = () => {
        resolve(typeof request.result === "string" ? request.result : null);
      };
    });
  } finally {
    database.close();
  }
}

async function deleteBackgroundImageFromDb() {
  const database = await openBackgroundImageDb();
  try {
    await runBackgroundImageTransaction(database, "readwrite", (store) => {
      store.delete(BACKGROUND_IMAGE_KEY);
    });
  } finally {
    database.close();
  }
}

function runBackgroundImageTransaction(
  database: IDBDatabase,
  mode: IDBTransactionMode,
  action: (store: IDBObjectStore) => void
) {
  return new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(BACKGROUND_IMAGE_STORE_NAME, mode);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error("背景图存储失败"));
    action(transaction.objectStore(BACKGROUND_IMAGE_STORE_NAME));
  });
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          p: ({ children }) => <p>{children}</p>,
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
        {normalizeMathMarkdown(content)}
      </ReactMarkdown>
    </div>
  );
}

function normalizeMathMarkdown(content: string) {
  return normalizeAccidentalIndentedMarkdown(normalizeCompactMarkdownTables(content))
    .replace(
      /\\\[((?:.|\n)*?)\\\]/g,
      (_, formula: string) => `\n$$\n${formula.trim()}\n$$\n`
    )
    .replace(/\\\(((?:.|\n)*?)\\\)/g, (_, formula: string) => `$${formula.trim()}$`);
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
