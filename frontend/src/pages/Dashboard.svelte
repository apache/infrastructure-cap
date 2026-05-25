<script lang="ts">
  import { link } from "svelte-spa-router";
  import AuthGuard from "../components/AuthGuard.svelte";
  import QuestionList from "../components/QuestionList.svelte";
</script>

<svelte:head><title>CAP - Dashboard</title></svelte:head>

<AuthGuard let:user>
  <div class="d-flex align-items-center justify-content-between mb-3">
    <h2 class="h4 mb-0">Dashboard</h2>
    {#if user.projects.length > 0}
      <a class="btn btn-primary" href="/question/new" use:link>
        <i class="fa-solid fa-circle-plus me-1"></i>New question
      </a>
    {/if}
  </div>
  <QuestionList {user} />
</AuthGuard>
