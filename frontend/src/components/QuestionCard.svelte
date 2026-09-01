<script lang="ts">
  import { link } from "svelte-spa-router";
  import type { Question } from "../lib/types";
  import { formatLocal, formatRelative, secondsRemaining } from "../lib/time";
  import {
    PENDING_RESOLUTION_LABEL,
    closedAt,
    isPendingResolution,
    pendingResolutionTooltip,
  } from "../lib/status";
  import CountdownBadge from "./CountdownBadge.svelte";
  import PrivacyBadge from "./PrivacyBadge.svelte";

  export let question: Question;
  // When true, hide the "Respond" call-to-action: the viewer can read the
  // question but is not allowed to submit a response (e.g. anonymous
  // dashboard mode).
  export let readOnly: boolean = false;

  // A question keeps `status === "open"` until it is resolved, but the
  // backend rejects responses the moment closes_at passes (409
  // deadline_passed), same as ResponseForm guards against. Offering
  // "Respond" on such a card points the viewer at a guaranteed error, so
  // treat a passed deadline as closed and fall back to "View tally".
  // CountdownBadge fires `closed` when the deadline elapses while the
  // dashboard is open, which flips this live.
  let deadlinePassed = secondsRemaining(question.closes_at) <= 0;
  // Recompute when the list refresh swaps new data into the same card.
  $: deadlinePassed = secondsRemaining(question.closes_at) <= 0;

  // Still accepting responses from this viewer?
  $: canRespond = !readOnly && question.status === "open" && !deadlinePassed;

  // The in-between state: voting is over, but the requester has yet to
  // resolve or withdraw, so the question is neither "Open" nor carrying
  // an outcome yet. Marking it "Open" here overstates what the viewer
  // can still do with it.
  $: pendingResolution = isPendingResolution(question, deadlinePassed);

  $: outcomeClass = pendingResolution
    ? "status-pending-resolution"
    : question.status === "open"
      ? "status-open"
      : question.status === "removed"
        ? "status-removed"
        : `status-resolved-${question.outcome ?? "approved"}`;

  $: outcomeLabel = pendingResolution
    ? PENDING_RESOLUTION_LABEL
    : question.status === "open"
      ? "Open"
      : question.status === "removed"
        ? "Withdrawn"
        : question.outcome === "approved"
          ? "Approved"
          : question.outcome === "vetoed"
            ? "Vetoed"
            : question.outcome === "insufficient_votes"
              ? "Insufficient votes"
              : "Closed";

  $: outcomeIcon = pendingResolution
    ? "fa-solid fa-hourglass-half text-info"
    : question.status === "open"
      ? "fa-regular fa-clock"
      : question.outcome === "approved"
        ? "fa-solid fa-check text-success"
        : question.outcome === "vetoed"
          ? "fa-solid fa-ban text-danger"
          : question.outcome === "insufficient_votes"
            ? "fa-solid fa-triangle-exclamation text-warning"
            : "fa-solid fa-xmark text-muted";

  // Native title tooltip (the app does not initialize Bootstrap's JS
  // tooltips anywhere), spelling out who the question is waiting on.
  $: outcomeTooltip = pendingResolution
    ? pendingResolutionTooltip(question)
    : null;

  // Age markers. "Filed" is always available; "closed" only once the
  // question has stopped taking responses, which is the deadline for
  // every question the viewer can date (see `closedAt`). Both carry the
  // absolute local timestamp as a native tooltip, since the relative
  // form is the scannable one but the exact time is what people quote.
  $: filedAgo = formatRelative(question.created_at);
  $: filedTooltip = `Filed ${formatLocal(question.created_at)}`;
  $: closedTimestamp = closedAt(question, deadlinePassed);
  $: closedAgo = closedTimestamp ? formatRelative(closedTimestamp) : null;
  $: closedTooltip = closedTimestamp
    ? `Voting closed ${formatLocal(closedTimestamp)}`
    : null;
</script>

<div class="card q-card {outcomeClass} mb-2">
  <div class="card-body py-3">
    <div class="d-flex justify-content-between align-items-start gap-3">
      <div class="flex-grow-1">
        <h5 class="mb-1">
          <a href="/question/{question.question_id}" use:link>
            {question.title}
          </a>
        </h5>
        <div class="small text-muted">
          <code class="code-inline">{question.project_id}</code>
          &middot; filed by <strong>{question.requester}</strong>
          &middot; for {question.target_audience}
        </div>
        <div class="mt-2 d-flex flex-wrap gap-2 align-items-center">
          <PrivacyBadge isPrivate={question.is_private} />
          {#if question.viewer_is_binding}
            <span class="badge bg-primary"
              ><i class="fa-solid fa-gavel me-1"></i>your vote is binding</span
            >
          {/if}
          <span class="small text-muted" title={outcomeTooltip}>
            <i class={outcomeIcon}></i>
            {outcomeLabel}
          </span>
          <span class="small text-muted" title={filedTooltip}>
            <i class="fa-solid fa-calendar-plus me-1"></i>filed {filedAgo}
          </span>
          {#if closedAgo}
            <span class="small text-muted" title={closedTooltip}>
              <i class="fa-solid fa-flag-checkered me-1"></i>closed {closedAgo}
            </span>
          {/if}
        </div>
      </div>
      <div class="text-end">
        {#if question.status === "open"}
          <div class="mb-2">
            <CountdownBadge
              closesAt={question.closes_at}
              initialSeconds={question.time_remaining_seconds}
              on:closed={() => (deadlinePassed = true)}
            />
          </div>
        {/if}
        {#if canRespond}
          <a
            href="/question/{question.question_id}"
            class="btn btn-sm btn-primary"
            use:link
          >
            <i class="fa-solid fa-paper-plane me-1"></i>Respond
          </a>
        {:else}
          <a
            href="/question/{question.question_id}"
            class="btn btn-sm btn-outline-secondary"
            use:link
          >
            {question.status === "open" && !deadlinePassed
              ? "View"
              : "View tally"}
          </a>
        {/if}
      </div>
    </div>
  </div>
</div>
