<script lang="ts">
  import { onMount } from "svelte";
  import type { Question, UserSession, QuestionDetail } from "../lib/types";
  import { api } from "../lib/api";
  import { cacheQuestion, questionsCache } from "../lib/stores";
  import QuestionCard from "./QuestionCard.svelte";
  import ErrorAlert from "./ErrorAlert.svelte";

  export let user: UserSession;

  let allOpen: Question[] = [];
  let loading = true;
  let errorMsg: string | null = null;
  let activeTab: "awaiting" | "recent" = "awaiting";
  let filter = "";

  let recentResolved: Question[] = [];

  // Privileged viewers (root or members of the `tooling` committee) receive
  // every question from /list, including those outside their own projects.
  // The "All projects" switch lets them narrow the view back down to just
  // their own projects/committees without having to log out. Non-privileged
  // viewers always see only what the backend has already filtered for them,
  // so the switch is hidden for them.
  $: isPrivilegedViewer = user.isRoot || user.committees.includes("tooling");
  let showAllProjects = false;

  function isOwnProject(q: Question): boolean {
    return (
      user.projects.includes(q.project_id) ||
      user.committees.includes(q.project_id)
    );
  }

  async function load() {
    loading = true;
    errorMsg = null;
    try {
      const data = await api.list();
      allOpen = data.pending;
      // Best-effort: pull cached details for any resolved questions we already
      // know about, so the "Recent activity" tab can show some closed items
      // without making the dashboard wait on a per-id round trip.
      const recent: Question[] = [];
      for (const detail of $questionsCache.values()) {
        const q = detail.question;
        if (q.status === "open") continue;
        const closedAt = Date.parse(q.closes_at);
        if (Number.isFinite(closedAt) && Date.now() - closedAt < 30 * 86400 * 1000) {
          recent.push(q);
        }
      }
      recentResolved = recent;
    } catch (err) {
      errorMsg = err instanceof Error ? err.message : "Failed to load list";
    } finally {
      loading = false;
    }
  }

  function matchesFilter(q: Question, f: string): boolean {
    if (!f) return true;
    const needle = f.toLowerCase();
    return (
      q.title.toLowerCase().includes(needle) ||
      q.project_id.toLowerCase().includes(needle) ||
      q.requester.toLowerCase().includes(needle)
    );
  }

  // Awaiting tab scope: privileged viewers with the switch OFF see only
  // questions on their own projects/committees; everyone else sees the full
  // /list result (the backend has already filtered for non-privileged
  // viewers).
  $: inAwaitingScope = (q: Question) =>
    !isPrivilegedViewer || showAllProjects || isOwnProject(q);

  // Recent tab scope: same idea, but non-privileged viewers are additionally
  // restricted to their own projects (the dashboard's "Recent activity" tab
  // is project-local even for users whose /list contains questions targeted
  // at audiences they happen to be in).
  $: inRecentScope = (q: Question) =>
    isPrivilegedViewer && showAllProjects ? true : isOwnProject(q);

  // "Awaiting your response": open questions where the viewer is in the
  // audience (we let the backend decide who is in /list) and has not yet
  // responded. We can't tell from /list alone if the viewer responded;
  // fall back to "show all open" as a safe superset.
  $: awaiting = allOpen
    .filter(inAwaitingScope)
    .filter((q) => matchesFilter(q, filter))
    .sort(
      (a, b) =>
        Date.parse(a.closes_at) - Date.parse(b.closes_at) ||
        a.question_id - b.question_id,
    );

  // "Recent activity": open questions plus any resolved/removed entries we
  // have in cache. Project-scoped per `inRecentScope`.
  $: recent = [...allOpen, ...recentResolved]
    .filter(inRecentScope)
    .filter((q) => matchesFilter(q, filter))
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));

  onMount(load);
</script>

<div>
  <ul class="nav nav-tabs" role="tablist">
    <li class="nav-item">
      <button
        type="button"
        class="nav-link {activeTab === 'awaiting' ? 'active' : ''}"
        on:click={() => (activeTab = "awaiting")}
      >
        <i class="fa-solid fa-inbox me-1"></i>
        Awaiting your response
        <span class="badge bg-secondary ms-1">{awaiting.length}</span>
      </button>
    </li>
    <li class="nav-item">
      <button
        type="button"
        class="nav-link {activeTab === 'recent' ? 'active' : ''}"
        on:click={() => (activeTab = "recent")}
      >
        <i class="fa-solid fa-clock-rotate-left me-1"></i>
        Recent activity
        <span class="badge bg-secondary ms-1">{recent.length}</span>
      </button>
    </li>
    <li class="nav-item ms-auto d-flex align-items-center gap-2 p-2">
      <input
        type="search"
        class="form-control form-control-sm"
        placeholder="Filter by title or project..."
        bind:value={filter}
      />
      {#if isPrivilegedViewer}
        <div
          class="form-check form-switch mb-0"
          title="Show questions from every project. When off, only questions on your own projects or committees are shown."
        >
          <input
            class="form-check-input"
            type="checkbox"
            role="switch"
            id="cap-all-projects-switch"
            bind:checked={showAllProjects}
          />
          <label
            class="form-check-label small text-nowrap"
            for="cap-all-projects-switch">All projects</label
          >
        </div>
      {/if}
      <button
        type="button"
        class="btn btn-sm btn-outline-secondary"
        title="Refresh"
        on:click={load}
      >
        <i class="fa-solid fa-arrows-rotate"></i>
      </button>
    </li>
  </ul>

  <div class="border border-top-0 rounded-bottom p-3 bg-white">
    {#if loading}
      <div class="spin-center">
        <i class="fa-solid fa-circle-notch fa-spin me-2"></i>Loading...
      </div>
    {:else if errorMsg}
      <ErrorAlert
        title="Could not load questions"
        message={errorMsg}
        onRetry={load}
      />
    {:else if activeTab === "awaiting"}
      {#if awaiting.length === 0}
        <div class="empty-state">
          <div class="empty-icon">
            <i class="fa-solid fa-mug-saucer"></i>
          </div>
          <h5>Nothing awaiting your response.</h5>
          <p class="small">
            You have no open questions to vote on. New questions will appear
            here when they arrive.
          </p>
        </div>
      {:else}
        {#each awaiting as q (q.question_id)}
          <QuestionCard question={q} />
        {/each}
      {/if}
    {:else if recent.length === 0}
      <div class="empty-state">
        <div class="empty-icon">
          <i class="fa-regular fa-folder-open"></i>
        </div>
        <h5>No recent activity.</h5>
        <p class="small">
          Questions from your projects and committees over the past 30 days
          will appear here.
        </p>
      </div>
    {:else}
      {#each recent as q (q.question_id)}
        <QuestionCard question={q} />
      {/each}
    {/if}
  </div>
</div>
