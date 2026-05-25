<script lang="ts">
  export let title: string = "Something went wrong.";
  export let message: string | null = null;
  export let onRetry: (() => void) | null = null;
</script>

<div class="alert alert-danger d-flex align-items-start" role="alert">
  <i class="fa-solid fa-circle-exclamation me-2 mt-1"></i>
  <div class="flex-grow-1">
    <div><strong>{title}</strong></div>
    {#if message}
      <div class="small">{message}</div>
    {/if}
  </div>
  {#if onRetry}
    <button
      type="button"
      class="btn btn-sm btn-outline-danger ms-3"
      on:click={onRetry}
    >
      <i class="fa-solid fa-rotate-right me-1"></i>Retry
    </button>
  {/if}
</div>
