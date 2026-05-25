<script lang="ts">
  import type { StoredResponse } from "../lib/types";
  import { formatLocal, formatRelative } from "../lib/time";

  export let responses: StoredResponse[];

  // Mark each row as "superseded" if a later row exists from the same voter.
  $: ranked = (() => {
    const latestByVoter = new Map<string, string>();
    for (const r of responses) {
      const prev = latestByVoter.get(r.voter);
      if (!prev || Date.parse(r.created_at) > Date.parse(prev)) {
        latestByVoter.set(r.voter, r.created_at);
      }
    }
    return responses.map((r) => ({
      r,
      superseded: latestByVoter.get(r.voter) !== r.created_at,
    }));
  })();

  function summarize(r: StoredResponse): string {
    if (r.response.kind === "vote") return r.response.value;
    if (r.response.kind === "lazy_consensus")
      return r.response.objection ? "Objection" : "No objection";
    return r.response.text.length > 80
      ? r.response.text.slice(0, 80) + "..."
      : r.response.text;
  }
</script>

<div class="card">
  <div class="card-header bg-white">
    <strong>Responses</strong>
    <span class="text-muted small ms-1">({responses.length})</span>
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
      {#each ranked as row (row.r.response_id)}
        <li class="list-group-item timeline-row" class:superseded={row.superseded}>
          <div class="d-flex justify-content-between align-items-start">
            <div>
              <span class="voter">
                <a
                  href="https://whimsy.apache.org/roster/committer/{row.r.voter}"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {row.r.voter}
                </a>
              </span>
              <span class="badge bg-{row.r.is_binding ? 'primary' : 'secondary'} ms-2">
                {row.r.is_binding ? "binding" : "non-binding"}
              </span>
              {#if row.r.is_veto}
                <span class="badge bg-danger ms-1">
                  <i class="fa-solid fa-ban me-1"></i>veto
                </span>
              {/if}
              {#if row.superseded}
                <span class="badge bg-light text-muted border ms-1"
                  >superseded</span
                >
              {/if}
              <div class="small mt-1">
                <code class="code-inline">{summarize(row.r)}</code>
                {#if row.r.comment}
                  &mdash; <span class="text-muted">{row.r.comment}</span>
                {/if}
              </div>
            </div>
            <div
              class="text-muted small text-end"
              title={row.r.created_at}
            >
              <div>{formatRelative(row.r.created_at)}</div>
              <div class="text-nowrap">{formatLocal(row.r.created_at)}</div>
            </div>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>
