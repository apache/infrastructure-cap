<script lang="ts">
  import {
    COMMENT_PREVIEW_MAX_CHARS,
    COMMENT_PREVIEW_MAX_LINES,
  } from "../lib/limits";

  // A comment body. Rendered in full when short; collapsed behind a
  // "Show more" toggle when it exceeds either the character or the line
  // budget. The ellipsis marks where the text was cut.
  export let text: string;

  let expanded = false;

  $: lines = text.split("\n");
  $: needsTruncation =
    text.length > COMMENT_PREVIEW_MAX_CHARS ||
    lines.length > COMMENT_PREVIEW_MAX_LINES;

  // Clip to whichever limit bites first: first N lines, then cap to the
  // character budget, then trim trailing whitespace so the ellipsis sits
  // flush against the last visible character.
  $: preview = (() => {
    const byLines = lines.slice(0, COMMENT_PREVIEW_MAX_LINES).join("\n");
    const clipped =
      byLines.length > COMMENT_PREVIEW_MAX_CHARS
        ? byLines.slice(0, COMMENT_PREVIEW_MAX_CHARS)
        : byLines;
    return clipped.replace(/\s+$/, "");
  })();
</script>

{#if needsTruncation && !expanded}
  <span class="text-muted comment-body">{preview}…</span>
  <button
    type="button"
    class="btn btn-link btn-sm p-0 align-baseline comment-toggle"
    on:click={() => (expanded = true)}
  >
    Show more
  </button>
{:else}
  <span class="text-muted comment-body">{text}</span>
  {#if needsTruncation}
    <button
      type="button"
      class="btn btn-link btn-sm p-0 align-baseline comment-toggle"
      on:click={() => (expanded = false)}
    >
      Show less
    </button>
  {/if}
{/if}

<style>
  /* Preserve authored line breaks and wrap long unbroken runs. */
  .comment-body {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .comment-toggle {
    margin-left: 0.35rem;
  }
</style>
