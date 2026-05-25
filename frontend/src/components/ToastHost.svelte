<script lang="ts">
  import { toasts, dismissToast } from "../lib/stores";
</script>

<div class="toast-host" aria-live="polite" aria-atomic="true">
  {#each $toasts as toast (toast.id)}
    <div
      class="toast show align-items-center text-white bg-{toast.level} border-0"
      role="alert"
    >
      <div class="d-flex">
        <div class="toast-body">{toast.message}</div>
        <button
          type="button"
          class="btn-close btn-close-white me-2 m-auto"
          aria-label="Close"
          on:click={() => dismissToast(toast.id)}
        ></button>
      </div>
    </div>
  {/each}
</div>
