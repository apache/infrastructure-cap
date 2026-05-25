import { writable, type Writable } from "svelte/store";
import type { QuestionDetail, UserSession } from "./types";

export type SessionState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "ready"; user: UserSession }
  | { status: "error"; message: string };

export const session: Writable<SessionState> = writable({ status: "loading" });

const MAX_CACHE = 50;
const cache: Map<number, QuestionDetail> = new Map();
export const questionsCache: Writable<Map<number, QuestionDetail>> = writable(
  cache,
);

export function cacheQuestion(detail: QuestionDetail): void {
  if (cache.size >= MAX_CACHE) {
    const firstKey = cache.keys().next().value;
    if (firstKey !== undefined) cache.delete(firstKey);
  }
  cache.set(detail.question.question_id, detail);
  questionsCache.set(cache);
}

export function invalidateQuestion(id: number): void {
  cache.delete(id);
  questionsCache.set(cache);
}

export interface Toast {
  id: number;
  level: "success" | "info" | "warning" | "danger";
  message: string;
  ttlMs: number;
}

let toastSeq = 1;
export const toasts: Writable<Toast[]> = writable([]);

export function pushToast(
  level: Toast["level"],
  message: string,
  ttlMs: number = 4000,
): void {
  const id = toastSeq++;
  toasts.update((list) => [...list, { id, level, message, ttlMs }]);
  if (ttlMs > 0) {
    setTimeout(() => {
      toasts.update((list) => list.filter((t) => t.id !== id));
    }, ttlMs);
  }
}

export function dismissToast(id: number): void {
  toasts.update((list) => list.filter((t) => t.id !== id));
}
