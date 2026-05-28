<script lang="ts">
  import { onMount } from "svelte";
  import { link } from "svelte-spa-router";
  import QuestionList from "../components/QuestionList.svelte";
  import ErrorAlert from "../components/ErrorAlert.svelte";
  import { session } from "../lib/stores";

  // Anonymous visitors get a brief introduction above the dashboard.
  // The dismissed state is stored in localStorage so the banner stays
  // hidden after the user closes it, even across reloads. We initialize
  // to ``true`` (hidden) until onMount reads the persisted value, so
  // there is no flicker on first paint for returning visitors.
  const WELCOME_DISMISSED_KEY = "cap.welcomeDismissed";
  let welcomeDismissed = true;

  onMount(() => {
    try {
      welcomeDismissed =
              window.localStorage.getItem(WELCOME_DISMISSED_KEY) === "1";
    } catch {
      // localStorage may be unavailable (private mode, disabled storage,
      // etc.); fall back to showing the banner.
      welcomeDismissed = false;
    }
  });

  function dismissWelcome(): void {
    welcomeDismissed = true;
    try {
      window.localStorage.setItem(WELCOME_DISMISSED_KEY, "1");
    } catch {
      // Best-effort persistence; ignore.
    }
  }
</script>

<svelte:head><title>CAP - Dashboard</title></svelte:head>

{#if $session.status === "loading"}
  <div class="spin-center" role="status" aria-live="polite">
    <i class="fa-solid fa-circle-notch fa-spin fa-2x me-2"></i>
    <span>Loading session...</span>
  </div>
{:else if $session.status === "error"}
  <ErrorAlert
          title="Could not load session"
          message={$session.message}
  />
{:else}
  {#if $session.status === "anonymous" && !welcomeDismissed}
    <div class="card mb-3 border-primary-subtle">
      <div class="card-body position-relative">
        <button
                type="button"
                class="btn-close position-absolute top-0 end-0 m-2"
                aria-label="Dismiss introduction"
                on:click={dismissWelcome}
        ></button>
        <h2 class="h5 mb-2">
          <i class="fa-solid fa-feather-pointed me-2 text-primary"></i>
          Welcome to the ASF's Contingent Approval Platform
        </h2>
        <p class="mb-1">
          This site hosts a fully auditable demo archive of
          decision-making events from projects at the Apache Software
          Foundation.
        </p>
        <p class="mb-2 text-muted small">
          The archive of public project decisions is open for the public
          to view, but interacting with the decision-making process is
          limited to committers and committee members of the respective
          projects.
        </p>
        <p class="mb-0 small">
          <a href="/about" use:link>
            <i class="fa-solid fa-circle-info me-1"></i>Learn more about CAP
          </a>
        </p>
      </div>
    </div>
  {/if}
  <div class="d-flex align-items-center justify-content-between mb-3">
    <h2 class="h4 mb-0">Dashboard</h2>
    {#if $session.status === "ready" && $session.user.projects.length > 0}
      <a class="btn btn-primary" href="/question/new" use:link>
        <i class="fa-solid fa-circle-plus me-1"></i>New question
      </a>
    {/if}
  </div>
  <QuestionList
          user={$session.status === "ready" ? $session.user : null}
  />
{/if}
