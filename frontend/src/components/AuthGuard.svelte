<script lang="ts">
  import { onMount } from "svelte";
  import { session } from "../lib/stores";
  import { redirectToLogin } from "../lib/auth";

  let redirected = false;

  $: if ($session.status === "anonymous" && !redirected) {
    redirected = true;
    redirectToLogin();
  }
</script>

{#if $session.status === "ready"}
  <slot user={$session.user} />
{:else if $session.status === "loading"}
  <div class="spin-center" role="status" aria-live="polite">
    <i class="fa-solid fa-circle-notch fa-spin fa-2x me-2"></i>
    <span>Loading session...</span>
  </div>
{:else if $session.status === "anonymous"}
  <div class="spin-center" role="status" aria-live="polite">
    <i class="fa-solid fa-circle-notch fa-spin fa-2x me-2"></i>
    <span>Redirecting to ASF login...</span>
  </div>
{:else if $session.status === "error"}
  <div class="alert alert-danger" role="alert">
    <i class="fa-solid fa-circle-exclamation me-2"></i>
    Could not load session: {$session.message}
  </div>
{/if}
