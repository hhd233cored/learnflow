export type GoalPayload = {
  title: string;
  exam_date: string;
  daily_minutes: number;
  current_level: string;
  key_topics: string[];
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

export type KnowledgeSearchHit = {
  content: string;
  metadata: Record<string, unknown>;
  distance?: number | null;
};

export type GoalDetail = {
  id: number;
  title: string;
  exam_date: string;
  daily_minutes: number;
  current_level: string;
  key_topics: string[];
  plans: StudyPlan[];
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

  getGoal(goalId: number) {
    return request<GoalDetail>(`/goals/${goalId}`);
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

  uploadMaterial(goalId: number, file: File) {
    const body = new FormData();
    body.append("file", file);
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

  listMaterials(goalId: number) {
    return request<CourseMaterial[]>(`/goals/${goalId}/materials`);
  },

  searchKnowledge(goalId: number, query: string, topK = 5) {
    return request<{ hits: KnowledgeSearchHit[] }>(
      `/goals/${goalId}/knowledge/search`,
      {
        method: "POST",
        body: JSON.stringify({ query, top_k: topK })
      }
    );
  }
};
