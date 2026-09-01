<script lang="ts">
  import { onMount } from "svelte";
  import type { Question, UserSession } from "../lib/types";
  import { api } from "../lib/api";
  import { lastActivityAt } from "../lib/status";
  import { secondsRemaining } from "../lib/time";
  import QuestionCard from "./QuestionCard.svelte";
  import ErrorAlert from "./ErrorAlert.svelte";
  import Pagination from "./Pagination.svelte";

  // Rows per page. Lists at or below this length render whole, with no
  // page controls at all (see Pagination).
  const PAGE_SIZE = 5;

  // ``null`` means the viewer is anonymous (no session). In that case the
  // list is sourced from /api/publist (which only ever returns public
  // questions) and every action button on a card is hidden via the
  // ``readOnly`` flag on QuestionCard.
  export let user: UserSession | null;

  let allOpen: Question[] = [];
  let allRecent: Question[] = [];
  let loading = true;
  let errorMsg: string | null = null;
  let activeTab: "awaiting" | "recent" = "awaiting";
  let filter = "";
  // One page cursor per tab, so switching tabs does not scroll the other
  // list back to its top. Both are 1-based.
  let awaitingPage = 1;
  let recentPage = 1;

  // Anything that re-partitions the lists (a new filter, a scope change,
  // a refetch) makes the old page numbers meaningless: page 3 of a
  // 40-question list is nowhere in a 4-question one. Start over at the
  // top instead of showing the viewer an empty page.
  function resetPages(): void {
    awaitingPage = 1;
    recentPage = 1;
  }

  // The pane holding the rows. Paging from the control *below* a full
  // page of cards would otherwise leave the viewer at the bottom of the
  // new page, looking at its last row.
  let pane: HTMLDivElement | undefined;

  function goToPage(which: "awaiting" | "recent", page: number): void {
    if (which === "awaiting") awaitingPage = page;
    else recentPage = page;
    pane?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Privileged viewers (root or members of the `tooling` committee) receive
  // every question from /list, including those outside their own projects.
  // The "All projects" switch lets them narrow the view back down to just
  // their own projects/committees without having to log out. Non-privileged
  // viewers always see only what the backend has already filtered for them,
  // so the switch is hidden for them. Anonymous viewers always see every
  // public question and the switch is meaningless to them.
  $: isPrivilegedViewer =
    !!user && (user.isRoot || user.committees.includes("tooling"));
  let showAllProjects = false;

  function isOwnProject(q: Question): boolean {
    if (!user) return false;
    return (
      user.projects.includes(q.project_id) ||
      user.committees.includes(q.project_id)
    );
  }

  async function load() {
    loading = true;
    errorMsg = null;
    resetPages();
    try {
      if (user) {
        const data = await api.list();
        allOpen = data.pending;
        // `recent` is populated server-side with every question (any
        // status) updated in the past 14 days, ACL-filtered. The
        // QuestionCard renders the open / resolved / withdrawn marker
        // straight from `status` and `outcome` per row.
        allRecent = data.recent ?? [];
      } else {
        // Anonymous mode: /api/publist is the only feed we are allowed
        // to hit. It returns one flat array — open questions first
        // (soonest-to-close), then closed-within-14-days. We split it
        // back into `allOpen` and `allRecent` so the rest of the
        // component can stay uniform.
        const data = await api.publicList();
        const questions = data.questions ?? [];
        allOpen = questions.filter((q) => q.status === "open");
        allRecent = questions;
      }
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
  // at audiences they happen to be in). Anonymous viewers have no project
  // scope at all, so every public question passes.
  $: inRecentScope = (q: Question) =>
    !user
      ? true
      : isPrivilegedViewer && showAllProjects
        ? true
        : isOwnProject(q);

  // When the SPA is in anonymous mode there is no "your" inbox, so the
  // Awaiting tab is suppressed and Recent becomes the only view.
  $: if (!user && activeTab === "awaiting") activeTab = "recent";

  // "Awaiting your response": open questions where the viewer is in the
  // audience (we let the backend decide who is in /list). Questions the
  // viewer has already answered stay in the list rather than vanishing,
  // because a response can be amended while the question is open; the
  // card marks them from `viewer_has_responded` and offers "Update
  // response" instead of "Respond".
  //
  // `status === "open"` is not the same as "still taking responses": the
  // backend refuses responses from `closes_at` onwards, so a question
  // whose deadline has passed sits in this list waiting on its requester,
  // not on the viewer. Those sort below everything still actionable,
  // however soon the actionable ones close. Within the live group the
  // soonest deadline leads (it is the most urgent); within the closed
  // group the most recently closed leads (it is the freshest). The clock
  // is read when the list is (re)computed, so a question crossing its
  // deadline while the dashboard sits open re-sorts on the next refresh.
  $: awaiting = allOpen
    .filter(inAwaitingScope)
    .filter((q) => matchesFilter(q, filter))
    .sort((a, b) => {
      const aLive = secondsRemaining(a.closes_at) > 0;
      const bLive = secondsRemaining(b.closes_at) > 0;
      if (aLive !== bLive) return aLive ? -1 : 1;
      return aLive
        ? Date.parse(a.closes_at) - Date.parse(b.closes_at) ||
            a.question_id - b.question_id
        : Date.parse(b.closes_at) - Date.parse(a.closes_at) ||
            b.question_id - a.question_id;
    });

  // "Recent activity": every question (open or closed) updated in the
  // past 14 days, as served by the backend's `recent` array. Project-
  // scoped per `inRecentScope`. Sorted reverse-chronologically on the
  // question's last visible state change (`lastActivityAt`): a question
  // that just closed and one that was just filed both sort to the top,
  // which is what "recent activity" means. `question_id` descending
  // breaks ties so the order is stable across refetches.
  $: recent = allRecent
    .filter(inRecentScope)
    .filter((q) => matchesFilter(q, filter))
    .sort(
      (a, b) =>
        Date.parse(lastActivityAt(b)) - Date.parse(lastActivityAt(a)) ||
        b.question_id - a.question_id,
    );

  // The cursor actually rendered. A list can shrink under its page
  // between renders (a question resolves out of scope, a refresh returns
  // fewer rows), so the stored cursor is clamped on the way out rather
  // than written back: page 4 of a list that just lost its tail shows
  // the new last page instead of an empty pane.
  $: awaitingCursor = Math.min(
    awaitingPage,
    Math.max(1, Math.ceil(awaiting.length / PAGE_SIZE)),
  );
  $: recentCursor = Math.min(
    recentPage,
    Math.max(1, Math.ceil(recent.length / PAGE_SIZE)),
  );

  $: awaitingPageRows = awaiting.slice(
    (awaitingCursor - 1) * PAGE_SIZE,
    awaitingCursor * PAGE_SIZE,
  );
  $: recentPageRows = recent.slice(
    (recentCursor - 1) * PAGE_SIZE,
    recentCursor * PAGE_SIZE,
  );

  onMount(load);
</script>

<div>
  <ul class="nav nav-tabs" role="tablist">
    {#if user}
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
    {/if}
    <li class="nav-item">
      <button
        type="button"
        class="nav-link {activeTab === 'recent' ? 'active' : ''}"
        on:click={() => (activeTab = "recent")}
      >
        <i class="fa-solid fa-clock-rotate-left me-1"></i>
        {user ? "Recent activity" : "Public questions"}
        <span class="badge bg-secondary ms-1">{recent.length}</span>
      </button>
    </li>
    <li class="nav-item ms-auto d-flex align-items-center gap-2 p-2">
      <input
        type="search"
        class="form-control form-control-sm"
        placeholder="Filter by title or project..."
        bind:value={filter}
        on:input={resetPages}
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
            on:change={resetPages}
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

  <div class="border border-top-0 rounded-bottom p-3 bg-white" bind:this={pane}>
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
        <Pagination
          variant="top"
          page={awaitingCursor}
          total={awaiting.length}
          pageSize={PAGE_SIZE}
          label="Awaiting your response pages"
          onChange={(p) => goToPage("awaiting", p)}
        />
        {#each awaitingPageRows as q (q.question_id)}
          <QuestionCard question={q} readOnly={!user} />
        {/each}
        <Pagination
          variant="bottom"
          page={awaitingCursor}
          total={awaiting.length}
          pageSize={PAGE_SIZE}
          label="Awaiting your response pages"
          onChange={(p) => goToPage("awaiting", p)}
        />
      {/if}
    {:else if recent.length === 0}
      <div class="empty-state">
        <div class="empty-icon">
          <i class="fa-regular fa-folder-open"></i>
        </div>
        {#if user}
          <h5>No recent activity.</h5>
          <p class="small">
            Questions from your projects and committees updated in the past
            14 days will appear here, with a marker showing whether each
            is still open or already closed.
          </p>
        {:else}
          <h5>No public questions to show.</h5>
          <p class="small">
            Public CAP questions that are still open or were updated in the
            past 14 days will appear here.
          </p>
        {/if}
      </div>
    {:else}
      <Pagination
        variant="top"
        page={recentCursor}
        total={recent.length}
        pageSize={PAGE_SIZE}
        label={user ? "Recent activity pages" : "Public questions pages"}
        onChange={(p) => goToPage("recent", p)}
      />
      {#each recentPageRows as q (q.question_id)}
        <QuestionCard question={q} readOnly={!user} />
      {/each}
      <Pagination
        variant="bottom"
        page={recentCursor}
        total={recent.length}
        pageSize={PAGE_SIZE}
        label={user ? "Recent activity pages" : "Public questions pages"}
        onChange={(p) => goToPage("recent", p)}
      />
    {/if}
  </div>
</div>
