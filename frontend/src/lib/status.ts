// Shared vocabulary for the "voting is over, nobody has resolved it yet"
// state. A question keeps `status === "open"` until the requester (or
// root) resolves or withdraws it, but the backend stops accepting
// responses the moment closes_at passes (409 deadline_passed). Both the
// dashboard card and the question detail page have to describe that
// window, and they must describe it the same way.

import type { Question } from "./types";
import { secondsRemaining } from "./time";

export const PENDING_RESOLUTION_LABEL = "Voting closed, pending resolution";

// `deadlinePassed` lets a caller that already tracks the deadline live
// (via CountdownBadge's `closed` event) pass its own flag in, so the
// label flips the second the timer runs out. Omit it to read the clock
// once at render time.
export function isPendingResolution(
  question: Question,
  deadlinePassed?: boolean,
): boolean {
  return (
    question.status === "open" &&
    (deadlinePassed ?? secondsRemaining(question.closes_at) <= 0)
  );
}

export function pendingResolutionTooltip(question: Question): string {
  return (
    `Voting closed at the deadline. This question is waiting for ` +
    `${question.requester} to resolve or withdraw it.`
  );
}

// When the question stopped accepting responses, or `null` while it is
// still taking them. The API surfaces no resolution timestamp
// (`updated_at` is persistence-only, per backend SPEC §7.1), but it does
// not need to: the backend refuses every response from `closes_at`
// onwards, and only root may resolve a question before that moment, so
// the deadline is the instant a closed question closed. A question that
// was withdrawn (or root-resolved) while the clock was still running has
// no viewer-visible closing time at all, hence `null`.
export function closedAt(
  question: Question,
  deadlinePassed?: boolean,
): string | null {
  const passed = deadlinePassed ?? secondsRemaining(question.closes_at) <= 0;
  return passed ? question.closes_at : null;
}

// The timestamp the dashboard sorts a question on: the last state change
// the viewer can see, which is either its closing or its filing.
export function lastActivityAt(question: Question): string {
  return closedAt(question) ?? question.created_at;
}
