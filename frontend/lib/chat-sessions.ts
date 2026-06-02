import type { ChatMessage } from "@/lib/api";

export type ChatSessionContextType = "general" | "goal" | "plan" | "pdf";

export type ChatSessionContext = {
  type: ChatSessionContextType;
  goalId?: number;
  planId?: number;
  materialId?: number;
  pageIndex?: number;
};

export type ChatSession = {
  id: string;
  title: string;
  context: ChatSessionContext;
  createdAt: string;
  updatedAt: string;
};

const SESSION_INDEX_KEY = "studyagent:chatSessions:index";
const ACTIVE_SESSION_KEY = "studyagent:chatSessions:activeId";
const SESSION_DB_NAME = "studyagent-chat-sessions";
const SESSION_STORE_NAME = "messages";
const DEFAULT_TITLE = "新会话";

export function listChatSessions(): ChatSession[] {
  const raw = window.localStorage.getItem(SESSION_INDEX_KEY);
  if (!raw) {
    return [];
  }

  try {
    const sessions = JSON.parse(raw) as Partial<ChatSession>[];
    return sessions
      .filter(isValidSession)
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  } catch {
    window.localStorage.removeItem(SESSION_INDEX_KEY);
    return [];
  }
}

export function getActiveChatSessionId(): string | null {
  return window.localStorage.getItem(ACTIVE_SESSION_KEY);
}

export function setActiveChatSessionId(sessionId: string | null) {
  if (sessionId) {
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  } else {
    window.localStorage.removeItem(ACTIVE_SESSION_KEY);
  }
}

export function createChatSession(
  context: ChatSessionContext,
  title = DEFAULT_TITLE
): ChatSession {
  const now = new Date().toISOString();
  const session: ChatSession = {
    id: createSessionId(),
    title,
    context,
    createdAt: now,
    updatedAt: now
  };

  saveChatSessionIndex([session, ...listChatSessions()]);
  setActiveChatSessionId(session.id);
  return session;
}

export function updateChatSession(
  sessionId: string,
  patch: Partial<Omit<ChatSession, "id" | "createdAt">>
): ChatSession | null {
  const sessions = listChatSessions();
  const index = sessions.findIndex((session) => session.id === sessionId);
  if (index < 0) {
    return null;
  }

  const updated: ChatSession = {
    ...sessions[index],
    ...patch,
    updatedAt: patch.updatedAt ?? new Date().toISOString()
  };
  sessions[index] = updated;
  saveChatSessionIndex(sessions);
  return updated;
}

export async function deleteChatSession(sessionId: string) {
  saveChatSessionIndex(listChatSessions().filter((session) => session.id !== sessionId));
  if (getActiveChatSessionId() === sessionId) {
    setActiveChatSessionId(null);
  }
  await deleteChatMessages(sessionId);
}

export async function getChatMessages(sessionId: string): Promise<ChatMessage[]> {
  const database = await openChatSessionDb();
  try {
    return await new Promise<ChatMessage[]>((resolve, reject) => {
      const transaction = database.transaction(SESSION_STORE_NAME, "readonly");
      const store = transaction.objectStore(SESSION_STORE_NAME);
      const request = store.get(sessionId);
      request.onerror = () => reject(request.error ?? new Error("读取会话失败"));
      request.onsuccess = () => {
        resolve(normalizeMessages(request.result));
      };
    });
  } finally {
    database.close();
  }
}

export async function saveChatMessages(
  sessionId: string,
  messages: ChatMessage[]
): Promise<void> {
  const database = await openChatSessionDb();
  try {
    await runMessageTransaction(database, "readwrite", (store) => {
      store.put(messages, sessionId);
    });
  } finally {
    database.close();
  }
}

function saveChatSessionIndex(sessions: ChatSession[]) {
  const unique = new Map<string, ChatSession>();
  for (const session of sessions) {
    unique.set(session.id, session);
  }
  const sorted = [...unique.values()].sort((left, right) =>
    right.updatedAt.localeCompare(left.updatedAt)
  );
  window.localStorage.setItem(SESSION_INDEX_KEY, JSON.stringify(sorted));
}

function createSessionId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `session_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

function isValidSession(item: Partial<ChatSession>): item is ChatSession {
  return (
    typeof item.id === "string" &&
    typeof item.title === "string" &&
    typeof item.createdAt === "string" &&
    typeof item.updatedAt === "string" &&
    typeof item.context === "object" &&
    item.context !== null &&
    isValidContextType(item.context.type)
  );
}

function isValidContextType(value: unknown): value is ChatSessionContextType {
  return value === "general" || value === "goal" || value === "plan" || value === "pdf";
}

function normalizeMessages(value: unknown): ChatMessage[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (message): message is ChatMessage =>
      Boolean(message) &&
      typeof message === "object" &&
      ((message as ChatMessage).role === "user" ||
        (message as ChatMessage).role === "assistant") &&
      typeof (message as ChatMessage).content === "string"
  );
}

function openChatSessionDb() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("当前浏览器不支持 IndexedDB，无法保存会话记录"));
      return;
    }

    const request = indexedDB.open(SESSION_DB_NAME, 1);
    request.onerror = () => reject(request.error ?? new Error("打开会话数据库失败"));
    request.onsuccess = () => resolve(request.result);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(SESSION_STORE_NAME)) {
        database.createObjectStore(SESSION_STORE_NAME);
      }
    };
  });
}

function deleteChatMessages(sessionId: string) {
  return openChatSessionDb().then(async (database) => {
    try {
      await runMessageTransaction(database, "readwrite", (store) => {
        store.delete(sessionId);
      });
    } finally {
      database.close();
    }
  });
}

function runMessageTransaction(
  database: IDBDatabase,
  mode: IDBTransactionMode,
  action: (store: IDBObjectStore) => void
) {
  return new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(SESSION_STORE_NAME, mode);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error("会话存储失败"));
    action(transaction.objectStore(SESSION_STORE_NAME));
  });
}
