<script lang="ts">
  import type { StoredResponse } from "../lib/types";
  import ResponseRow from "./ResponseRow.svelte";

  export let responses: StoredResponse[];

  let sortDesc = true;

  $: sorted = [...responses].sort((a, b) =>
    sortDesc
      ? Date.parse(b.created_at) - Date.parse(a.created_at)
      : Date.parse(a.created_at) - Date.parse(b.created_at),
  );

  // A current response renders inline; a run of consecutive superseded
  // responses by one voter is collapsed into an expandable rollup.
  type TimelineItem =
    | { kind: "current"; response: StoredResponse }
    | { kind: "rollup"; voter: string; responses: StoredResponse[] };

  // Mark each row as "superseded" if a later row exists from the same voter.
  $: ranked = (() => {
    const latestByVoter = new Map<string, string>();
    for (const r of sorted) {
      const prev = latestByVoter.get(r.voter);
      if (!prev || Date.parse(r.created_at) > Date.parse(prev)) {
        latestByVoter.set(r.voter, r.created_at);
      }
    }
    return sorted.map((r) => ({
      r,
      superseded: latestByVoter.get(r.voter) !== r.created_at,
    }));
  })();

  // Walk the ordered rows and collapse each maximal run of consecutive
  // superseded responses from the same voter into one rollup.
  // Current responses (and runs broken by a different voter) stay distinct.
  $: items = ((): TimelineItem[] => {
    const out: TimelineItem[] = [];
    let i = 0;
    while (i < ranked.length) {
      if (ranked[i].superseded) {
        const voter = ranked[i].r.voter;
        const run: StoredResponse[] = [];
        while (
          i < ranked.length &&
          ranked[i].superseded &&
          ranked[i].r.voter === voter
        ) {
          run.push(ranked[i].r);
          i++;
        }
        out.push({ kind: "rollup", voter, responses: run });
      } else {
        out.push({ kind: "current", response: ranked[i].r });
        i++;
      }
    }
    return out;
  })();

  // Keyed by the first response in a rollup so the toggle state is stable
  // across re-renders.
  let expanded = new Set<string>();
  function toggle(key: string) {
    if (expanded.has(key)) expanded.delete(key);
    else expanded.add(key);
    expanded = expanded;
  }

  const itemKey = (item: TimelineItem): string =>
    item.kind === "current"
      ? item.response.response_id
      : `rollup-${item.responses[0].response_id}`;
</script>

<div class="card">
  <div class="card-header bg-white d-flex justify-content-between align-items-center">
    <div>
      <strong>Responses</strong>
      <span class="text-muted small ms-1">({responses.length})</span>
    </div>
    {#if responses.length > 1}
      <button
        type="button"
        class="btn btn-sm btn-link p-0 text-decoration-none text-muted"
        on:click={() => (sortDesc = !sortDesc)}
        title={sortDesc ? "Switch to oldest first" : "Switch to newest first"}
      >
        <i class="fa-solid fa-clock me-1"></i>{sortDesc ? "Newest first" : "Oldest first"}
      </button>
    {/if}
  </div>
  {#if responses.length === 0}
    <div class="card-body empty-state">
      <div class="empty-icon">
        <i class="fa-regular fa-comments"></i>
      </div>
      <div>No responses yet.</div>
    </div>
  {:else}
    <ul class="list-group list-group-flush">
      {#each items as item (itemKey(item))}
        {@const key = itemKey(item)}
        {@const open = expanded.has(key)}
        <li class="list-group-item">
          {#if item.kind === "current"}
            <ResponseRow response={item.response} />
          {:else}
            <button
              type="button"
              class="btn btn-link btn-sm p-0 text-decoration-none rollup-toggle"
              aria-expanded={open}
              on:click={() => toggle(key)}
            >
              <i
                class="fa-solid fa-chevron-{open ? 'down' : 'right'} me-1 small"
              ></i>
              <i class="fa-solid fa-clock-rotate-left me-1"></i>
              {open ? "Hide" : "Show"}
              {item.responses.length}
              earlier {item.responses.length === 1 ? "response" : "responses"}
              by {item.voter}
            </button>
            {#if open}
              <ul class="list-unstyled mb-0 mt-2 ps-3 rollup-body">
                {#each item.responses as r (r.response_id)}
                  <li class="py-2">
                    <ResponseRow response={r} />
                  </li>
                {/each}
              </ul>
            {/if}
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .rollup-toggle {
    font-weight: 500;
  }
  .rollup-body {
    border-left: 2px solid var(--bs-border-color, #dee2e6);
    opacity: 0.7;
  }
  .rollup-body li + li {
    border-top: 1px solid var(--bs-border-color, #dee2e6);
  }
</style>
