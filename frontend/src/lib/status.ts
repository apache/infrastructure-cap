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
