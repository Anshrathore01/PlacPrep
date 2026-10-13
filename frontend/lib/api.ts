import type { AIRequest, AIResponse, AnalyticsSummary, Attempt, Company, Blueprint, MockTest, PlacoResponse, Question, QuestionListItem, SubjectTrack, User } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
function getToken() { return typeof window === "undefined" ? null : localStorage.getItem("prepwise_token"); }
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const token = getToken(); if (token) headers.set("Authorization", `Bearer ${token}`);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), path === "/ai/placo/chat" ? 60_000 : 15_000);
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers,
      signal: init.signal ?? controller.signal,
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(0, "The request timed out. Please try again.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    if (response.status >= 500) {
      message = "Unable to complete your request right now. Please try again.";
      if (path === "/ai/placo/chat" && response.status === 503) {
        try {
          const body = await response.json();
          if (typeof body.detail === "string") message = body.detail;
        } catch {}
      }
    } else {
      try {
        const body = await response.json();
        if (typeof body.detail === "string") {
          message = body.detail;
        } else if (Array.isArray(body.detail)) {
          message = body.detail
            .map((issue: { msg?: unknown; loc?: unknown[] }) => {
              const field = Array.isArray(issue.loc) ? issue.loc.at(-1) : undefined;
              return typeof issue.msg === "string"
                ? `${typeof field === "string" ? `${field}: ` : ""}${issue.msg}`
                : "";
            })
            .filter(Boolean)
            .join("; ") || message;
        } else if (typeof body.detail?.message === "string") {
          message = body.detail.message;
        }
      } catch {}
    }
    if (response.status === 401 && typeof window !== "undefined") localStorage.removeItem("prepwise_token");
    throw new ApiError(response.status, message);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const api = {
  login: (body: { email: string; password: string }) => request<{ access_token: string }>("/auth/login", { method: "POST", body: JSON.stringify(body) }),
  register: (body: { email: string; password: string; display_name: string }) => request<User>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  me: () => request<User>("/auth/me"),
  questions: (params = "") => request<QuestionListItem[]>(`/questions${params}`),
  codingPractice: () => request<{ service_companies: string[]; sections: { title: string; problems: { id: string; number: number; title: string; url: string }[] }[]; solved_problem_ids: string[]; authenticated: boolean }>("/coding-practice/catalog"),
  setCodingProblemSolved: (id: string, is_solved: boolean) => request<{ problem_id: string; is_solved: boolean }>(`/coding-practice/progress/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ is_solved }) }),
  question: (id: number) => request<Question>(`/questions/${id}`),
  mocks: (id: number) => request<MockTest & { questions?: Question[] }>(`/mock-tests/${id}`),
  createMock: (body: Record<string, unknown>) => request<MockTest>("/mock-tests", { method: "POST", body: JSON.stringify(body) }),
  attempt: async (id: number) => {
    const response = await request<Attempt | { attempt: Attempt; questions: Attempt["questions"] }>(`/attempts/${id}`);
    if ("attempt" in response) return { ...response.attempt, questions: response.questions } as Attempt;
    return response;
  },
  startAttempt: (mock_test_id: number, duration_seconds?: number) => request<Attempt>("/attempts", { method: "POST", body: JSON.stringify({ mock_test_id, duration_seconds }) }),
  saveAnswer: (id: number, body: { question_id: number; selected_option_key?: string; answer_text?: string; time_spent_seconds: number }) => request<Record<string, unknown>>(`/attempts/${id}/answers`, { method: "POST", body: JSON.stringify(body) }),
  submitAttempt: (id: number) => request<Attempt>(`/attempts/${id}/submit`, { method: "POST" }),
  summary: () => request<AnalyticsSummary>("/analytics/me/summary"),
  topics: () => request<Record<string, unknown>[]>("/analytics/me/topics"),
  difficulty: () => request<Record<string, unknown>[]>("/analytics/me/difficulty"),
  progress: () => request<Record<string, unknown>>("/analytics/me/progress"),
  attempts: () => request<Record<string, unknown>>("/analytics/me/attempts"),
  companies: () => request<Company[]>("/companies"),
  company: (id: number) => request<Company>(`/companies/${id}`),
  blueprints: () => request<Blueprint[]>("/blueprints"),
  generateAI: (body: AIRequest) => request<AIResponse>("/ai/mock-tests/generate", { method: "POST", body: JSON.stringify(body) }),
  taxonomy: () => request<SubjectTrack[]>("/taxonomy"),
  placo: (body: { message: string; question_id?: number; attempt_id?: number; conversation_id?: number }) => request<PlacoResponse>("/ai/placo/chat", { method: "POST", body: JSON.stringify(body) }),
};
