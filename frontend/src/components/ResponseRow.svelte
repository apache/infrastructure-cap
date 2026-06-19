<script lang="ts">
  import type { StoredResponse } from "../lib/types";
  import { formatLocal, formatRelative } from "../lib/time";
  import ExpandableComment from "./ExpandableComment.svelte";

  export let response: StoredResponse;

  function summarize(r: StoredResponse): string {
    if (r.response.kind === "vote") return r.response.value;
    if (r.response.kind === "lazy_consensus")
      return r.response.objection ? "Objection" : "No objection";
    return r.response.text.length > 80
      ? r.response.text.slice(0, 80) + "..."
      : r.response.text;
  }
</script>

<div class="d-flex justify-content-between align-items-start timeline-row">
  <div>
    <span class="voter">
      <a
        href="https://whimsy.apache.org/roster/committer/{response.voter}"
        target="_blank"
        rel="noopener noreferrer"
      >
        {response.voter}
      </a>
    </span>
    <span class="badge bg-{response.is_binding ? 'primary' : 'secondary'} ms-2">
      {response.is_binding ? "binding" : "non-binding"}
    </span>
    {#if response.is_veto}
      <span class="badge bg-danger ms-1">
        <i class="fa-solid fa-ban me-1"></i>veto
      </span>
    {/if}
    <div class="small mt-1">
      <code class="code-inline">{summarize(response)}</code>
      {#if response.comment}
        &mdash; <ExpandableComment text={response.comment} />
      {/if}
    </div>
  </div>
  <div class="text-muted small text-end" title={response.created_at}>
    <div>{formatRelative(response.created_at)}</div>
    <div class="text-nowrap">{formatLocal(response.created_at)}</div>
  </div>
</div>
