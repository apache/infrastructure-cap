import { config } from "./config";
import { redirectToLogin } from "./auth";
import type {
  CreateQuestionRequest,
  EditQuestionRequest,
  ErrorMessage,
  ListResponse,
  Question,
  QuestionDetail,
  ResolutionRecord,
  StoredResponse,
  SubmittedResponse,
  UserSession,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: ErrorMessage | null,
    message?: string,
  ) {
    super(message ?? `HTTP ${status}`);
  }
}

export class NotFoundError extends ApiError {}
export class ConflictError extends ApiError {}
export class ForbiddenError extends ApiError {}
export class UnauthorizedError extends ApiError {}

// POST /question/{id}/responses landed in the backend (section 9.7).
export const RESPONSE_SUBMISSION_ENABLED = true;

async function readJsonSafely(res: Response): Promise<ErrorMessage | null> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as ErrorMessage;
  } catch {
    return { error: "non_json_response", message: text } as ErrorMessage;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  let payload: string | undefined;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const res = await fetch(`${config.API_BASE}${path}`, {
    method,
    headers,
    credentials: "include",
    body: payload,
  });

  if (res.status === 204) {
    return undefined as unknown as T;
  }

  if (res.ok) {
    if (res.headers.get("content-type")?.includes("application/json")) {
      return (await res.json()) as T;
    }
    return undefined as unknown as T;
  }

  const errorBody = await readJsonSafely(res);

  if (
    res.status === 401 &&
    (errorBody?.error === "authentication_required" || !errorBody)
  ) {
    redirectToLogin();
    throw new UnauthorizedError(401, errorBody);
  }
  if (res.status === 403) throw new ForbiddenError(403, errorBody);
  if (res.status === 404) throw new NotFoundError(404, errorBody);
  if (res.status === 409) throw new ConflictError(409, errorBody);
  throw new ApiError(res.status, errorBody);
}

export const api = {
  getSession: () => request<UserSession | ErrorMessage>("GET", "/auth"),
  list: () => request<ListResponse>("GET", "/list"),
  createQuestion: (body: CreateQuestionRequest) =>
    request<Question>("POST", "/question", body),
  getQuestion: (id: number) =>
    request<QuestionDetail>("GET", `/question/${id}`),
  editQuestion: (id: number, body: EditQuestionRequest) =>
    request<Question>("PATCH", `/question/${id}`, body),
  withdrawQuestion: (id: number) =>
    request<void>("DELETE", `/question/${id}`),
  resolveQuestion: (id: number) =>
    request<Question>("POST", `/question/${id}/resolve`),
  submitResponse: (id: number, body: SubmittedResponse) =>
    request<StoredResponse>("POST", `/question/${id}/responses`, body),
  getResolution: (id: number) =>
    request<ResolutionRecord>("GET", `/resolution/${id}`),
};
