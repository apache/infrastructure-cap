<script lang="ts">
  import { onMount } from "svelte";
  import { link, push } from "svelte-spa-router";
  import AuthGuard from "../components/AuthGuard.svelte";
  import QuestionForm from "../components/QuestionForm.svelte";
  import ErrorAlert from "../components/ErrorAlert.svelte";
  import { api, ApiError, NotFoundError } from "../lib/api";
  import type { Question, QuestionDetail, UserSession } from "../lib/types";

  export let params: { id: string };

  let detail: QuestionDetail | null = null;
  let loading = true;
  let notFound = false;
  let errorMsg: string | null = null;

  async function load() {
    loading = true;
    notFound = false;
    errorMsg = null;
    try {
      const id = Number.parseInt(params.id, 10);
      if (!Number.isFinite(id)) {
        notFound = true;
        return;
      }
      detail = await api.getQuestion(id);
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

  function canEdit(q: Question, user: UserSession): boolean {
    return q.status === "open" && (q.requester === user.uid || user.isRoot);
  }
</script>

<svelte:head>
  <title>CAP - Edit {detail?.question.title ?? "question"}</title>
</svelte:head>

<AuthGuard let:user>
  {#if loading}
    <div class="spin-center">
      <i class="fa-solid fa-circle-notch fa-spin me-2"></i>Loading...
    </div>
  {:else if notFound}
    <div class="empty-state">
      <div class="empty-icon"><i class="fa-solid fa-folder-minus"></i></div>
      <h4>Question not found.</h4>
      <a class="btn btn-outline-secondary" href="/" use:link>
        Back to dashboard
      </a>
    </div>
  {:else if errorMsg}
    <ErrorAlert title="Could not load" message={errorMsg} onRetry={load} />
  {:else if detail && !canEdit(detail.question, user)}
    <div class="alert alert-warning">
      <i class="fa-solid fa-triangle-exclamation me-2"></i>
      You cannot edit this question. Only the original requester (or root) may
      edit, and only while the question is open.
    </div>
    <a class="btn btn-outline-secondary" href="/question/{detail.question.question_id}" use:link>
      Back to question
    </a>
  {:else if detail}
    <h2 class="h4 mb-3">
      <i class="fa-solid fa-pen-to-square me-1"></i>
      Edit question #{detail.question.question_id}
    </h2>
    <QuestionForm mode="edit" {user} question={detail.question} />
  {/if}
</AuthGuard>
