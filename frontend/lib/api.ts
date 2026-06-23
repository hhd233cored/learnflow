export type GoalPayload = {
  title: string;
  goal_type: "exam" | "duration";
  exam_date?: string | null;
  duration_days?: number | null;
  daily_minutes: number;
  current_level: string;
  key_topics: string[];
};

export type Job = {
  id: number;
  goal_id?: number | null;
  job_type: string;
  status: "pending" | "running" | "success" | "failed";
  progress: number;
  result_json?: Record<string, unknown> | null;
  error_message?: string | null;
  finished_at?: string | null;
};

export type StudyPlan = {
  id: number;
  day_index: number;
  plan_date: string;
  topic: string;
  objective: string;
  status: string;
  adjusted: boolean;
  adjustment_reason?: string | null;
};

export type StudyTask = {
  id: number;
  title: string;
  description: string;
  estimated_minutes: number;
  task_type: string;
  status: string;
};

export type QuizQuestion = {
  id: string;
  type: "single_choice" | "short_answer";
  question: string;
  options: string[];
  correct_answer?: string | null;
  reference_answer?: string | null;
  explanation: string;
};

export type QuizAnswerItem = {
  question_id: string;
  answer: string;
};

export type QuizResultItem = {
  question_id: string;
  is_correct: boolean;
  score: number;
  feedback: string;
  correct_answer?: string | null;
};

export type QuizResult = {
  score: number;
  items: QuizResultItem[];
  summary: string;
};

export type TaskQuiz = {
  id: number;
  task_id: number;
  plan_id: number;
  goal_id: number;
  status: string;
  source_mode: "rag" | "llm_fallback";
  questions: QuizQuestion[];
  answers: QuizAnswerItem[];
  result?: QuizResult | null;
  created_at: string;
  submitted_at?: string | null;
};

export type Review = {
  id: number;
  completion_rate: number;
  summary: string;
  weak_points: string[];
  suggestions: string[];
};

export type Adjustment = {
  id: number;
  from_day: number;
  original_topic: string;
  adjusted_topic: string;
  original_objective: string;
  adjusted_objective: string;
  reason: string;
};

export type CourseMaterial = {
  id: number;
  goal_id: number;
  filename: string;
  file_type: string;
  parse_status: string;
  error_message?: string | null;
  chunk_count: number;
  chroma_collection: string;
};

export type PdfMeta = {
  material_id: number;
  filename: string;
  page_count: number;
  readable_pages: number[];
};

export type PdfPageText = {
  material_id: number;
  filename: string;
  page_index: number;
  readable: boolean;
  text: string;
  text_hash: string;
};

export type PdfPageTranslation = {
  material_id: number;
  page_index: number;
  source_lang: string;
  target_lang: string;
  text_hash: string;
  translated_text: string;
  extraction_mode: "text" | "ocr";
  cached: boolean;
};

export type ReadingContext = {
  material_id: number;
  page_index: number;
};

export type KnowledgeSearchHit = {
  content: string;
  metadata: Record<string, unknown>;
  distance?: number | null;
  rerank_score?: number | null;
  lexical_score?: number | null;
  retrieval_source?: string | null;
};

export type KnowledgeSearchFilters = {
  material_id?: number;
  plan_id?: number;
  day_index?: number;
  source_type?: string;
};

export type KnowledgeSnippetPayload = {
  content: string;
  source_name: string;
  plan_id?: number;
  day_index?: number;
};

export type GoalDetail = {
  id: number;
  title: string;
  goal_type: "exam" | "duration";
  exam_date: string;
  duration_days?: number | null;
  daily_minutes: number;
  current_level: string;
  key_topics: string[];
  plans: StudyPlan[];
};

export type GoalSummary = {
  id: number;
  title: string;
  goal_type: "exam" | "duration";
  exam_date: string;
  duration_days?: number | null;
  daily_minutes: number;
  current_level: string;
  key_topics: string[];
  status: string;
  plan_count: number;
  material_count: number;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    ...init
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export const api = {
  createGoal(payload: GoalPayload) {
    return request<GoalDetail>("/goals", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  createGoalWithMaterials(payload: GoalPayload, files: File[]) {
    const body = new FormData();
    body.append("title", payload.title);
    body.append("goal_type", payload.goal_type);
    if (payload.exam_date) {
      body.append("exam_date", payload.exam_date);
    }
    if (payload.duration_days) {
      body.append("duration_days", String(payload.duration_days));
    }
    body.append("daily_minutes", String(payload.daily_minutes));
    body.append("current_level", payload.current_level);
    body.append("key_topics", payload.key_topics.join(","));
    files.forEach((file) => body.append("files", file));

    return fetch(`${API_BASE_URL}/goals/with-materials`, {
      method: "POST",
      body
    }).then(async (response) => {
      if (!response.ok) {
        throw new Error((await response.text()) || "Create goal failed");
      }
      return response.json() as Promise<GoalDetail>;
    });
  },

  createGoalWithMaterialsLocalJob(payload: GoalPayload, files: File[]) {
    const body = new FormData();
    body.append("title", payload.title);
    body.append("goal_type", payload.goal_type);
    if (payload.exam_date) {
      body.append("exam_date", payload.exam_date);
    }
    if (payload.duration_days) {
      body.append("duration_days", String(payload.duration_days));
    }
    body.append("daily_minutes", String(payload.daily_minutes));
    body.append("current_level", payload.current_level);
    body.append("key_topics", payload.key_topics.join(","));
    files.forEach((file) => body.append("files", file));

    return fetch(`${API_BASE_URL}/goals/with-materials/local-job`, {
      method: "POST",
      body
    }).then(async (response) => {
      if (!response.ok) {
        throw new Error((await response.text()) || "Create goal job failed");
      }
      return response.json() as Promise<Job>;
    });
  },

  createGoalAsync(payload: GoalPayload) {
    return request<Job>("/goals/async", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  getJob(jobId: number) {
    return request<Job>(`/jobs/${jobId}`);
  },

  getGoal(goalId: number) {
    return request<GoalDetail>(`/goals/${goalId}`);
  },

  listGoals() {
    return request<GoalSummary[]>("/goals");
  },

  deleteGoal(goalId: number) {
    return fetch(`${API_BASE_URL}/goals/${goalId}`, {
      method: "DELETE"
    }).then(async (response) => {
      if (!response.ok) {
        throw new Error((await response.text()) || "Delete goal failed");
      }
    });
  },

  regenerateGoalPlan(goalId: number) {
    return request<GoalDetail>(`/goals/${goalId}/plans/regenerate`, {
      method: "POST"
    });
  },

  getTasks(planId: number) {
    return request<StudyTask[]>(`/plans/${planId}/tasks`);
  },

  generateTasks(planId: number) {
    return request<StudyTask[]>(`/plans/${planId}/tasks/generate`, {
      method: "POST"
    });
  },

  updateTaskStatus(taskId: number, status: string) {
    return request<StudyTask>(`/tasks/${taskId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status })
    });
  },

  generateTaskQuiz(taskId: number, regenerate = false) {
    return request<TaskQuiz>(`/tasks/${taskId}/quiz`, {
      method: "POST",
      body: JSON.stringify({ regenerate })
    });
  },

  submitTaskQuiz(quizId: number, answers: QuizAnswerItem[]) {
    return request<TaskQuiz>(`/quizzes/${quizId}/submit`, {
      method: "POST",
      body: JSON.stringify({ answers })
    });
  },

  createReview(planId: number, feedback: string) {
    return request<Review>(`/plans/${planId}/review`, {
      method: "POST",
      body: JSON.stringify({ feedback })
    });
  },

  adjustTomorrow(goalId: number, fromDay: number) {
    return request<Adjustment>(`/goals/${goalId}/adjust`, {
      method: "POST",
      body: JSON.stringify({ from_day: fromDay })
    });
  },

  uploadMaterial(goalId: number, file: File, filters: KnowledgeSearchFilters = {}) {
    const body = new FormData();
    body.append("file", file);
    if (filters.plan_id) {
      body.append("plan_id", String(filters.plan_id));
    }
    if (filters.day_index) {
      body.append("day_index", String(filters.day_index));
    }
    return fetch(`${API_BASE_URL}/goals/${goalId}/materials/upload`, {
      method: "POST",
      body
    }).then(async (response) => {
      if (!response.ok) {
        throw new Error((await response.text()) || "Upload failed");
      }
      return response.json() as Promise<CourseMaterial>;
    });
  },

  uploadReaderPdf(goalId: number, file: File) {
    const body = new FormData();
    body.append("file", file);
    body.append("build_knowledge", "false");
    return fetch(`${API_BASE_URL}/goals/${goalId}/materials/upload`, {
      method: "POST",
      body
    }).then(async (response) => {
      if (!response.ok) {
        throw new Error((await response.text()) || "Upload PDF failed");
      }
      return response.json() as Promise<CourseMaterial>;
    });
  },

  listMaterials(goalId: number) {
    return request<CourseMaterial[]>(`/goals/${goalId}/materials`);
  },

  ocrMaterial(materialId: number) {
    return request<CourseMaterial>(`/materials/${materialId}/ocr`, {
      method: "POST"
    });
  },

  deleteMaterial(materialId: number) {
    return fetch(`${API_BASE_URL}/materials/${materialId}`, {
      method: "DELETE"
    }).then(async (response) => {
      if (!response.ok) {
        throw new Error((await response.text()) || "Delete material failed");
      }
    });
  },

  createKnowledgeSnippet(goalId: number, payload: KnowledgeSnippetPayload) {
    return request<CourseMaterial>(`/goals/${goalId}/knowledge/snippets`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  searchKnowledge(
    goalId: number,
    query: string,
    topK = 5,
    filters: KnowledgeSearchFilters = {}
  ) {
    return request<{ hits: KnowledgeSearchHit[] }>(
      `/goals/${goalId}/knowledge/search`,
      {
        method: "POST",
        body: JSON.stringify({ query, top_k: topK, ...filters })
      }
    );
  },

  async streamChat(payload: {
    messages: ChatMessage[];
    goal_id?: number;
    plan_id?: number;
    reading_context?: ReadingContext | null;
  }) {
    const response = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!response.ok || !response.body) {
      throw new Error((await response.text()) || "Chat request failed");
    }
    return response.body.getReader();
  },

  compressChat(payload: { messages: ChatMessage[]; target_chars?: number }) {
    return request<{ message: ChatMessage; compressed: boolean; original_chars: number }>(
      "/chat/compress",
      {
        method: "POST",
        body: JSON.stringify(payload)
      }
    );
  },

  getPdfMeta(materialId: number) {
    return request<PdfMeta>(`/materials/${materialId}/pdf/meta`);
  },

  getPdfPageText(materialId: number, pageIndex: number) {
    return request<PdfPageText>(`/materials/${materialId}/pdf/pages/${pageIndex}/text`);
  },

  translatePdfPage(
    materialId: number,
    pageIndex: number,
    targetLanguage = "zh-CN",
    mode: "text" | "ocr" = "text"
  ) {
    return request<PdfPageTranslation>(
      `/materials/${materialId}/pdf/pages/${pageIndex}/translate`,
      {
        method: "POST",
        body: JSON.stringify({ target_language: targetLanguage, mode })
      }
    );
  },

  pdfPageImageUrl(materialId: number, pageIndex: number, zoom = 2) {
    return `${API_BASE_URL}/materials/${materialId}/pdf/pages/${pageIndex}/image?zoom=${zoom}`;
  }
};
