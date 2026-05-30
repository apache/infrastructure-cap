// TypeScript interfaces mirroring the Pydantic models in backend/SPEC.md.
// Any drift between these and the backend's OpenAPI document is a bug.

export interface UserSession {
  uid: string;
  fullname?: string | null;
  isRoot: boolean;
  projects: string[];
  committees: string[];
}

export type ApprovalType =
  | "unanimous_approval"
  | "majority_approval"
  | "simple_majority"
  | "lazy_consensus";

export type QuestionStatus = "open" | "resolved" | "removed";

export type QuestionOutcome =
  | "approved"
  | "vetoed"
  | "insufficient_votes"
  | "withdrawn";

export type VoteValue = "+1" | "+0" | "-0" | "-1";

export interface VoteOption {
  kind: "vote";
  allowed_values: VoteValue[];
  allow_comment: boolean;
}

export interface LazyConsensusOption {
  kind: "lazy_consensus";
  allow_comment: boolean;
}

export interface FreeTextOption {
  kind: "free_text";
  max_length: number;
}

export type ResponseOption = VoteOption | LazyConsensusOption | FreeTextOption;

export interface VoteResponse {
  kind: "vote";
  value: VoteValue;
  comment?: string | null;
}

export interface LazyConsensusResponse {
  kind: "lazy_consensus";
  objection: boolean;
  comment?: string | null;
}

export interface FreeTextResponse {
  kind: "free_text";
  text: string;
}

export type SubmittedResponse =
  | VoteResponse
  | LazyConsensusResponse
  | FreeTextResponse;

export interface Question {
  question_id: number;
  request_id: string;
  project_id: string;
  title: string;
  description: string;
  requester: string;
  target_audience: string;
  created_at: string;
  closes_at: string;
  approval_type: ApprovalType;
  is_binding: boolean;
  is_private: boolean;
  response_option: ResponseOption;
  permalink?: string | null;
  status: QuestionStatus;
  outcome?: QuestionOutcome | null;
  viewer_is_binding: boolean;
  time_remaining_seconds: number;
}

export interface StoredResponse {
  response_id: string;
  question_id: number;
  voter: string;
  response_kind: "vote" | "lazy_consensus" | "free_text";
  response: SubmittedResponse;
  comment?: string | null;
  is_binding: boolean;
  is_veto: boolean;
  created_at: string;
}

export interface ListResponse {
  user: string;
  // Open questions awaiting a response, soonest-to-close first.
  pending: Question[];
  // Every question (open or closed) the caller may view whose
  // updated_at falls within the past 14 days, most-recently-touched
  // first. Drives the "Recent activity" tab on the dashboard.
  recent: Question[];
}

// Body returned by GET /api/publist (SPEC §9.13). Non-private questions
// that are either still open or were updated in the past 14 days. Used
// by the dashboard when the SPA is in anonymous (not-logged-in) mode.
export interface PublicListResponse {
  questions: Question[];
}

export interface QuestionDetail {
  question: Question;
  responses: StoredResponse[];
}

export interface CreateQuestionRequest {
  project_id: string;
  title: string;
  description: string;
  target_audience: string;
  approval_type: ApprovalType;
  is_binding: boolean;
  is_private: boolean;
  response_option: ResponseOption;
  closes_at: string;
}

export interface EditQuestionRequest {
  title?: string;
  description?: string;
  target_audience?: string;
  closes_at?: string;
  is_private?: boolean;
  response_option?: ResponseOption;
}

export interface ResolutionRecord {
  question_id: number;
  outcome: QuestionOutcome;
  resolved_at: string;
  permalink: string;
  question: Question;
  tally: Record<string, unknown> | null;
  voters: StoredResponse[];
}

export interface ErrorMessage {
  error: string;
  message?: string;
  [key: string]: unknown;
}
