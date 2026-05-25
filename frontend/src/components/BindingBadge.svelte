<script lang="ts">
  export let binding: boolean;
</script>

{#if binding}
  <span
    class="badge bg-primary"
    title="Your vote will be binding on this question"
  >
    <i class="fa-solid fa-gavel me-1"></i>binding
  </span>
{:else}
  <span class="badge bg-secondary" title="Your vote is non-binding">
    <i class="fa-regular fa-circle me-1"></i>non-binding
  </span>
{/if}
