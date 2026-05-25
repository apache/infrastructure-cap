<script lang="ts">
  import { onMount } from "svelte";
  import { link } from "svelte-spa-router";
  import AuthGuard from "../components/AuthGuard.svelte";
  import ErrorAlert from "../components/ErrorAlert.svelte";
  import { api, ApiError, NotFoundError } from "../lib/api";
  import type { QuestionDetail, ResolutionRecord } from "../lib/types";
  import { formatLocal } from "../lib/time";

  export let params: { id: string };

  let record: ResolutionRecord | null = null;
  let fallbackDetail: QuestionDetail | null = null;
  let loading = true;
  let notFound = false;
  let errorMsg: string | null = null;
  let pending = false;

  async function load() {
    loading = true;
    notFound = false;
    errorMsg = null;
    pending = false;
    record = null;
    fallbackDetail = null;
    try {
      const id = Number.parseInt(params.id, 10);
      if (!Number.isFinite(id)) {
        notFound = true;
        return;
      }
      try {
        record = await api.getResolution(id);
      } catch (err) {
        if (err instanceof NotFoundError) {
          // /resolution returns 204 if open. The api wrapper resolves 204
          // as undefined, but Pydantic-modelled endpoints may also 404 if
          // not yet implemented; fall back to the question detail.
          fallbackDetail = await api.getQuestion(id);
          if (fallbackDetail.question.status === "open") pending = true;
        } else {
          throw err;
        }
      }
      if (!record) {
        // 204 case: api returns undefined for resolution; fall back.
        try {
          fallbackDetail = await api.getQuestion(id);
          if (fallbackDetail.question.status === "open") pending = true;
        } catch {
          // ignore; we'll surface notFound below if both fail
        }
      }
    } catch (err) {
      if (err instanceof NotFoundError) {
        notFound = true;
      } else if (err instanceof ApiError) {
        errorMsg = err.body?.message || `HTTP ${err.status}`;
      } else {
        errorMsg = err instanceof Error ? err.message : "Load failed";
      }
    } finally {
      loading = false;
    }
  }

  onMount(load);
</script>

<svelte:head>
  <title>CAP - Resolution #{params.id}</title>
</svelte:head>

<AuthGuard>
  {#if loading}
    <div class="spin-center">
      <i class="fa-solid fa-circle-notch fa-spin me-2"></i>Loading...
    </div>
  {:else if notFound}
    <div class="empty-state">
      <div class="empty-icon"><i class="fa-solid fa-folder-minus"></i></div>
      <h4>No such resolution.</h4>
      <a class="btn btn-outline-secondary" href="/" use:link
        >Back to dashboard</a
      >
    </div>
  {:else if errorMsg}
    <ErrorAlert title="Could not load resolution" message={errorMsg} onRetry={load} />
  {:else if record}
    <h2 class="h4 mb-3">
      Resolution &mdash; question #{record.question_id}
    </h2>
    <div class="alert alert-light border">
      <strong>Outcome:</strong>
      <span class="badge bg-{record.outcome === 'approved' ? 'success' : 'danger'}">
        {record.outcome}
      </span>
      <span class="text-muted ms-2">at {formatLocal(record.resolved_at)}</span>
    </div>
    <div class="mb-3">
      <a href="/question/{record.question_id}" use:link
        ><i class="fa-solid fa-arrow-left me-1"></i>Open question detail</a
      >
    </div>
    {#if record.tally}
      <pre class="bg-light p-3 small">{JSON.stringify(record.tally, null, 2)}</pre>
    {/if}
  {:else if pending && fallbackDetail}
    <div class="alert alert-info">
      <i class="fa-solid fa-circle-info me-2"></i>
      Question #{fallbackDetail.question.question_id} is still open. There is
      no resolution to display yet.
    </div>
    <a
      class="btn btn-outline-secondary"
      href="/question/{fallbackDetail.question.question_id}"
      use:link
    >
      View question
    </a>
  {/if}
</AuthGuard>
