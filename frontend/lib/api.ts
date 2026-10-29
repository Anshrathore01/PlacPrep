import type { AIRequest, AIResponse, AnalyticsSummary, Attempt, Company, Blueprint, MockTest, PlacoResponse, ProductDsaQuestion, Question, QuestionListItem, SubjectTrack, User } from "./types";
import { createSupabaseBrowserClient } from "./supabase/client";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL?.trim()
  || (process.env.NODE_ENV !== "production" ? "http://127.0.0.1:8000" : "");
const PUBLIC_DATA_TTL_MS = 5 * 60_000;
const publicDataCache = new Map<string, { expiresAt: number; promise: Promise<unknown> }>();
export class ApiError extends Error {
  constructor(public status: number, message: string, public retryAfterSeconds?: number) {
    super(message);
  }
}

function cachedPublicData<T>(key: string, load: () => Promise<T>): Promise<T> {
  const cached = publicDataCache.get(key);
  if (cached && cached.expiresAt > Date.now()) return cached.promise as Promise<T>;

  const entry = {
    expiresAt: Date.now() + PUBLIC_DATA_TTL_MS,
    promise: Promise.resolve(undefined) as Promise<unknown>,
  };
  const promise = load().catch((error) => {
    if (publicDataCache.get(key) === entry) publicDataCache.delete(key);
    throw error;
  });
  entry.promise = promise;
  publicDataCache.set(key, entry);
  return promise;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!BASE_URL) {
    throw new ApiError(0, "The API server is not configured. Set NEXT_PUBLIC_API_BASE_URL and rebuild the frontend.");
  }
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (typeof window !== "undefined") {
    const { data: { session } } = await createSupabaseBrowserClient().auth.getSession();
    if (session?.access_token) headers.set("Authorization", `Bearer ${session.access_token}`);
  }
  const controller = new AbortController();
  const timeoutMs = path.startsWith("/ai/") ? 60_000 : 35_000;
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
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
      throw new ApiError(0, "The server took too long to respond. If the backend is waking up, please retry shortly.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    const retryAfterHeader = response.headers.get("Retry-After");
    let retryAfterSeconds: number | undefined;
    if (retryAfterHeader) {
      const seconds = Number(retryAfterHeader);
      const dateDelay = Date.parse(retryAfterHeader) - Date.now();
      const delay = Number.isFinite(seconds) ? seconds : dateDelay / 1000;
      if (Number.isFinite(delay) && delay > 0) retryAfterSeconds = Math.ceil(delay);
    }
    let message = response.status >= 500
      ? "Unable to complete your request right now. Please try again."
      : `Request failed (${response.status})`;

    try {
      const body = await response.json();
      if (typeof body.detail === "string" && body.detail.trim()) {
        message = body.detail.trim();
      } else if (Array.isArray(body.detail)) {
        const issues = body.detail
          .map((issue: { msg?: unknown; loc?: unknown[] }) => {
            const field = Array.isArray(issue.loc) ? issue.loc.at(-1) : undefined;
            return typeof issue.msg === "string"
              ? `${typeof field === "string" ? `${field}: ` : ""}${issue.msg}`
              : "";
          })
          .filter(Boolean)
          .join("; ");
        if (issues) message = issues;
      } else if (typeof body.detail?.message === "string" && body.detail.message.trim()) {
        message = body.detail.message.trim();
      } else if (typeof body.message === "string" && body.message.trim()) {
        message = body.message.trim();
      }
    } catch {}

    if (response.status === 401 && typeof window !== "undefined") {
      void createSupabaseBrowserClient().auth.signOut({ scope: "local" });
    }
    throw new ApiError(response.status, message, retryAfterSeconds);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const api = {
  me: () => request<User>("/auth/me"),
  questions: (params = "") => request<QuestionListItem[]>(`/questions${params}`),
  codingPractice: () => request<{ service_companies: string[]; sections: { title: string; problems: { id: string; number: number; title: string; url: string }[] }[]; solved_problem_ids: string[]; authenticated: boolean }>("/coding-practice/catalog"),
  productDsaQuestions: () => request<{ questions: ProductDsaQuestion[]; total: number; completed: number; remaining: number }>("/coding-practice/product"),
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
  companies: () => cachedPublicData("companies", () => request<Company[]>("/companies")),
  company: (id: number) => request<Company>(`/companies/${id}`),
  blueprints: () => request<Blueprint[]>("/blueprints"),
  generateAI: (body: AIRequest) => request<AIResponse>("/ai/mock-tests/generate", { method: "POST", body: JSON.stringify(body) }),
  taxonomy: () => cachedPublicData("taxonomy", () => request<SubjectTrack[]>("/taxonomy")),
  placo: (body: { message: string; question_id?: number; attempt_id?: number; conversation_id?: number }) => request<PlacoResponse>("/ai/placo/chat", { method: "POST", body: JSON.stringify(body) }),
};
