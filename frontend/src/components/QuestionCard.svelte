<script lang="ts">
  import { link } from "svelte-spa-router";
  import type { Question } from "../lib/types";
  import CountdownBadge from "./CountdownBadge.svelte";
  import PrivacyBadge from "./PrivacyBadge.svelte";

  export let question: Question;

  $: outcomeClass =
    question.status === "open"
      ? "status-open"
      : question.status === "removed"
        ? "status-removed"
        : `status-resolved-${question.outcome ?? "approved"}`;

  $: outcomeLabel =
    question.status === "open"
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

  $: outcomeIcon =
    question.status === "open"
      ? "fa-regular fa-clock"
      : question.outcome === "approved"
        ? "fa-solid fa-check text-success"
        : question.outcome === "vetoed"
          ? "fa-solid fa-ban text-danger"
          : question.outcome === "insufficient_votes"
            ? "fa-solid fa-triangle-exclamation text-warning"
            : "fa-solid fa-xmark text-muted";
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
          <span class="small text-muted">
            <i class={outcomeIcon}></i>
            {outcomeLabel}
          </span>
        </div>
      </div>
      <div class="text-end">
        {#if question.status === "open"}
          <div class="mb-2">
            <CountdownBadge
              closesAt={question.closes_at}
              initialSeconds={question.time_remaining_seconds}
            />
          </div>
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
            View tally
          </a>
        {/if}
      </div>
    </div>
  </div>
</div>
