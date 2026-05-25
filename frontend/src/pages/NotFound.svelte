<script lang="ts">
  import { link } from "svelte-spa-router";
</script>

<svelte:head><title>CAP - Not found</title></svelte:head>

<div class="empty-state">
  <div class="empty-icon">
    <i class="fa-solid fa-compass"></i>
  </div>
  <h3>Page not found.</h3>
  <p>The URL you followed does not match any page in this app.</p>
  <a class="btn btn-primary" href="/" use:link>
    <i class="fa-solid fa-house me-1"></i>Return to dashboard
  </a>
</div>
