<script lang="ts">
  import type { Question, StoredResponse } from "../lib/types";
  import { previewTally } from "../lib/tally";
  import { pushToast } from "../lib/stores";
  import ExpandableComment from "./ExpandableComment.svelte";

  export let question: Question;
  export let responses: StoredResponse[];

  $: tally = previewTally(question, responses);

  async function copyPermalink() {
    if (!question.permalink) return;
    try {
      await navigator.clipboard.writeText(question.permalink);
      pushToast("success", "Permalink copied to clipboard.");
    } catch {
      pushToast("warning", "Could not copy to clipboard.");
    }
  }
</script>

<div class="card">
  <div class="card-header bg-white">
    <strong>
      {#if question.status === "open"}
        <i class="fa-regular fa-clock me-1"></i>Provisional tally
      {:else if question.status === "removed"}
        <i class="fa-solid fa-xmark me-1"></i>Withdrawn
      {:else if question.outcome === "approved"}
        <i class="fa-solid fa-check text-success me-1"></i>Approved
      {:else if question.outcome === "vetoed"}
        <i class="fa-solid fa-ban text-danger me-1"></i>Vetoed
      {:else if question.outcome === "insufficient_votes"}
        <i class="fa-solid fa-triangle-exclamation text-warning me-1"></i
        >Insufficient votes
      {/if}
    </strong>
    {#if question.status === "open"}
      <span class="text-muted small ms-2">Not yet resolved.</span>
    {/if}
  </div>

  <div class="card-body">
    {#if tally.kind === "unanimous_approval"}
      {#if tally.vetoes.length === 0}
        <div class="text-success">
          <i class="fa-solid fa-check me-1"></i>No veto in force.
        </div>
      {:else}
        <div class="text-danger mb-2">
          <i class="fa-solid fa-ban me-1"></i>{tally.vetoes.length} veto{tally
            .vetoes.length === 1
            ? ""
            : "es"} recorded.
        </div>
        <ul class="list-unstyled small mb-0">
          {#each tally.vetoes as veto}
            <li>
              <strong>{veto.voter}</strong>:
              {#if veto.comment}
                <ExpandableComment text={veto.comment} />
              {:else}
                <span class="text-muted">(no reason)</span>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
      <div
        class="small mt-2"
        class:text-success={tally.bindingPlus1 >= tally.minBindingPlus1}
        class:text-warning={tally.bindingPlus1 < tally.minBindingPlus1}
      >
        <i class="fa-solid fa-hashtag me-1"></i>
        Binding <code class="code-inline">+1</code>:
        {tally.bindingPlus1} / {tally.minBindingPlus1} required.
      </div>
    {:else if tally.kind === "majority_approval"}
      <div class="row g-3">
        <div class="col-md-6">
          <div class="small text-muted">Binding</div>
          <div class="d-flex gap-3">
            <span><code class="code-inline">+1</code> {tally.binding.plus1}</span>
            <span><code class="code-inline">+0</code> {tally.binding.plus0}</span>
            <span><code class="code-inline">-0</code> {tally.binding.minus0}</span>
            <span><code class="code-inline">-1</code> {tally.binding.minus1}</span>
          </div>
        </div>
        <div class="col-md-6">
          <div class="small text-muted">Non-binding</div>
          <div class="d-flex gap-3 text-muted">
            <span><code class="code-inline">+1</code> {tally.nonbinding.plus1}</span>
            <span><code class="code-inline">+0</code> {tally.nonbinding.plus0}</span>
            <span><code class="code-inline">-0</code> {tally.nonbinding.minus0}</span>
            <span><code class="code-inline">-1</code> {tally.nonbinding.minus1}</span>
          </div>
        </div>
      </div>
      <div
        class="small mt-2"
        class:text-success={tally.binding.plus1 >= tally.minBindingPlus1 &&
          tally.binding.plus1 > tally.binding.minus1}
        class:text-warning={!(
          tally.binding.plus1 >= tally.minBindingPlus1 &&
          tally.binding.plus1 > tally.binding.minus1
        )}
      >
        <i class="fa-solid fa-hashtag me-1"></i>
        Binding <code class="code-inline">+1</code>:
        {tally.binding.plus1} / {tally.minBindingPlus1} required, and must
        outnumber binding <code class="code-inline">-1</code>.
      </div>
    {:else if tally.kind === "simple_majority"}
      <div class="row g-3">
        <div class="col-md-6">
          <div class="small text-muted">Binding</div>
          <div class="d-flex gap-3">
            <span><code class="code-inline">+1</code> {tally.binding.plus1}</span>
            <span><code class="code-inline">+0</code> {tally.binding.plus0}</span>
            <span><code class="code-inline">-0</code> {tally.binding.minus0}</span>
            <span><code class="code-inline">-1</code> {tally.binding.minus1}</span>
          </div>
        </div>
        <div class="col-md-6">
          <div class="small text-muted">Non-binding</div>
          <div class="d-flex gap-3 text-muted">
            <span><code class="code-inline">+1</code> {tally.nonbinding.plus1}</span>
            <span><code class="code-inline">+0</code> {tally.nonbinding.plus0}</span>
            <span><code class="code-inline">-0</code> {tally.nonbinding.minus0}</span>
            <span><code class="code-inline">-1</code> {tally.nonbinding.minus1}</span>
          </div>
        </div>
      </div>
      <div
        class="small mt-2"
        class:text-success={tally.binding.plus1 > tally.binding.minus1}
        class:text-warning={tally.binding.plus1 <= tally.binding.minus1}
      >
        <i class="fa-solid fa-hashtag me-1"></i>
        Binding <code class="code-inline">+1</code> ({tally.binding.plus1})
        must strictly outnumber binding <code class="code-inline">-1</code>
        ({tally.binding.minus1}). No minimum-three-votes floor.
      </div>
    {:else if tally.kind === "lazy_consensus"}
      {#if tally.objections.length === 0}
        <div class="text-success">
          <i class="fa-solid fa-check me-1"></i>No objection raised. Silence
          is assent.
        </div>
      {:else}
        <div class="text-warning mb-2">
          <i class="fa-solid fa-triangle-exclamation me-1"></i>
          {tally.objections.length} objection{tally.objections.length === 1
            ? ""
            : "s"} recorded.
        </div>
        <ul class="list-unstyled small mb-0">
          {#each tally.objections as obj}
            <li>
              <strong>{obj.voter}</strong>:
              {#if obj.comment}
                <ExpandableComment text={obj.comment} />
              {:else}
                <span class="text-muted">(no comment)</span>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    {/if}

    {#if question.permalink}
      <hr />
      <div class="small">
        <span class="text-muted me-2">Permalink:</span>
        <a href={question.permalink}>{question.permalink}</a>
        <button
          type="button"
          class="btn btn-sm btn-link"
          on:click={copyPermalink}
          title="Copy to clipboard"
        >
          <i class="fa-regular fa-clipboard"></i>
        </button>
      </div>
    {/if}
  </div>
</div>
