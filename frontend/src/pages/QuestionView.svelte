<script lang="ts">
  import { onMount } from "svelte";
  import { link, push } from "svelte-spa-router";
  import TallyPanel from "../components/TallyPanel.svelte";
  import ResponseTimeline from "../components/ResponseTimeline.svelte";
  import ResponseForm from "../components/ResponseForm.svelte";
  import CountdownBadge from "../components/CountdownBadge.svelte";
  import PrivacyBadge from "../components/PrivacyBadge.svelte";
  import ErrorAlert from "../components/ErrorAlert.svelte";
  import {
    api,
    ApiError,
    NotFoundError,
  } from "../lib/api";
  import { cacheQuestion, invalidateQuestion, pushToast, session } from "../lib/stores";
  import { redirectToLogin } from "../lib/auth";
  import { formatLocal, secondsRemaining } from "../lib/time";
  import type {
    QuestionDetail,
    StoredResponse,
    UserSession,
  } from "../lib/types";

  export let params: { id: string };

  let detail: QuestionDetail | null = null;
  let loading = true;
  let notFound = false;
  let errorMsg: string | null = null;
  let id: number;

  // Tracks whether the closing deadline has elapsed. Backend reserves
  // early resolution (before closes_at) for root, so a non-root
  // requester resolving too early gets a 403 deadline_in_future. We
  // flip this on load and again when CountdownBadge fires its `closed`
  // event, so the Resolve button only enables once it can succeed.
  let deadlinePassed = false;

  // The current viewer if logged in, or null when the SPA is in
  // anonymous (read-only) mode. Mirrors the same convention used by
  // QuestionList. Action buttons (Edit / Resolve / Withdraw) and the
  // ResponseForm are hidden in anonymous mode.
  $: viewer = $session.status === "ready" ? $session.user : null;

  async function load() {
    loading = true;
    notFound = false;
    errorMsg = null;
    try {
      id = Number.parseInt(params.id, 10);
      if (!Number.isFinite(id)) {
        notFound = true;
        return;
      }
      detail = await api.getQuestion(id);
      deadlinePassed = secondsRemaining(detail.question.closes_at) <= 0;
      cacheQuestion(detail);
    } catch (err) {
      if (err instanceof NotFoundError) {
        notFound = true;
      } else if (err instanceof ApiError) {
        errorMsg =
          err.body?.message ||
          err.body?.error ||
          `Could not load question (HTTP ${err.status}).`;
      } else {
        errorMsg = err instanceof Error ? err.message : "Load failed";
      }
    } finally {
      loading = false;
    }
  }

  onMount(load);
  $: void (params, load());

  function canEdit(d: QuestionDetail, user: UserSession): boolean {
    return (
      d.question.status === "open" &&
      (d.question.requester === user.uid || user.isRoot)
    );
  }

  // Resolve can only succeed once the deadline has passed (or for root,
  // who may resolve early). Surfacing it before then just yields a 403.
  $: resolvable =
    !!detail &&
    !!viewer &&
    canEdit(detail, viewer) &&
    (viewer.isRoot || deadlinePassed);

  function viewerPrior(
    d: QuestionDetail,
    user: UserSession,
  ): StoredResponse | null {
    const mine = d.responses.filter((r) => r.voter === user.uid);
    if (mine.length === 0) return null;
    return mine.reduce((a, b) =>
      Date.parse(a.created_at) > Date.parse(b.created_at) ? a : b,
    );
  }

  async function onWithdraw() {
    if (!detail) return;
    if (!confirm("Withdraw this question? This cannot be undone.")) return;
    try {
      await api.withdrawQuestion(detail.question.question_id);
      invalidateQuestion(detail.question.question_id);
      pushToast("info", "Question withdrawn.");
      push("/");
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.body?.message || `HTTP ${err.status}`
          : err instanceof Error
            ? err.message
            : "Withdraw failed";
      pushToast("danger", msg);
    }
  }

  async function onResolve() {
    if (!detail) return;
    if (!confirm("Resolve this question now? This will compute the tally and freeze the result."))
      return;
    try {
      const resolved = await api.resolveQuestion(detail.question.question_id);
      invalidateQuestion(resolved.question_id);
      pushToast("success", `Question resolved: ${resolved.outcome}.`);
      await load();
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.body?.message || `HTTP ${err.status}`
          : err instanceof Error
            ? err.message
            : "Resolve failed";
      pushToast("danger", msg);
    }
  }
</script>

<svelte:head>
  <title>CAP - {detail?.question.title ?? "Question"}</title>
</svelte:head>

{#if loading || $session.status === "loading"}
  <div class="spin-center">
    <i class="fa-solid fa-circle-notch fa-spin me-2"></i>Loading...
  </div>
{:else if $session.status === "error"}
  <ErrorAlert
    title="Could not load session"
    message={$session.message}
  />
{:else if notFound}
  <div class="empty-state">
    <div class="empty-icon"><i class="fa-solid fa-folder-minus"></i></div>
    <h4>Question not found.</h4>
    <p class="small">
      This question does not exist, or you do not have permission to view it.
    </p>
    <a class="btn btn-outline-secondary" href="/" use:link>
      Back to dashboard
    </a>
  </div>
{:else if errorMsg}
  <ErrorAlert
    title="Could not load question"
    message={errorMsg}
    onRetry={load}
  />
{:else if detail}
  <div class="d-flex justify-content-between align-items-start mb-3 flex-wrap gap-2">
    <div>
      <div class="small text-muted">
        <code class="code-inline">{detail.question.project_id}</code>
        &middot; Question #{detail.question.question_id}
        &middot; filed by <strong>{detail.question.requester}</strong>
        &middot; {formatLocal(detail.question.created_at)}
      </div>
      <h2 class="h4 mb-1">{detail.question.title}</h2>
      <div class="d-flex flex-wrap gap-2 align-items-center">
        <PrivacyBadge isPrivate={detail.question.is_private} />
        {#if detail.question.status === "open"}
          <CountdownBadge
            closesAt={detail.question.closes_at}
            initialSeconds={detail.question.time_remaining_seconds}
            on:closed={() => (deadlinePassed = true)}
          />
        {/if}
        <span class="badge bg-light text-muted border">
          {detail.question.approval_type.replace(/_/g, " ")}
        </span>
        {#if detail.question.viewer_is_binding}
          <span class="badge bg-primary">
            <i class="fa-solid fa-gavel me-1"></i>your vote is binding
          </span>
        {/if}
      </div>
    </div>
    <div class="text-end">
      {#if viewer && canEdit(detail, viewer)}
        <a
          class="btn btn-outline-secondary btn-sm me-1"
          href="/question/{detail.question.question_id}/edit"
          use:link
        >
          <i class="fa-solid fa-pen-to-square me-1"></i>Edit
        </a>
        <button
          type="button"
          class="btn btn-outline-success btn-sm me-1"
          on:click={onResolve}
          disabled={!resolvable}
          title={resolvable
            ? "Resolve this question and compute the tally"
            : "Resolution is available once the closing deadline has passed"}
        >
          <i class="fa-solid fa-flag-checkered me-1"></i>Resolve
        </button>
        <button
          type="button"
          class="btn btn-outline-danger btn-sm"
          on:click={onWithdraw}
        >
          <i class="fa-solid fa-xmark me-1"></i>Withdraw
        </button>
      {/if}
    </div>
  </div>

  <div class="card mb-3">
    <div class="card-body">
      <h6 class="text-muted small mb-1">Description</h6>
      <div style="white-space: pre-wrap;">{detail.question.description}</div>
      <hr />
      <div class="row small text-muted g-2">
        <div class="col-md-6">
          <strong>Audience:</strong> {detail.question.target_audience}
        </div>
        <div class="col-md-6">
          <strong>Closes:</strong> {formatLocal(detail.question.closes_at)}
        </div>
      </div>
    </div>
  </div>

  <div class="row g-3">
    <div class="col-md-5">
      <TallyPanel
        question={detail.question}
        responses={detail.responses}
      />
    </div>
    <div class="col-md-7">
      {#if detail.question.status === "open"}
        {#if viewer}
          <ResponseForm
            question={detail.question}
            priorResponse={viewerPrior(detail, viewer)}
            on:submitted={load}
          />
        {:else}
          <div class="alert alert-info d-flex align-items-center" role="alert">
            <i class="fa-solid fa-right-to-bracket me-2"></i>
            <div class="flex-grow-1">
              You are browsing as a guest. Sign in with your ASF account
              to submit a response.
            </div>
            <button
              type="button"
              class="btn btn-sm btn-primary ms-2"
              on:click={() => redirectToLogin()}
            >
              Log in
            </button>
          </div>
        {/if}
      {/if}
      <div class="mt-3">
        <ResponseTimeline responses={detail.responses} />
      </div>
    </div>
  </div>
{/if}
