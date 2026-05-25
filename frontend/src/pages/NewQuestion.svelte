<script lang="ts">
  import AuthGuard from "../components/AuthGuard.svelte";
  import QuestionForm from "../components/QuestionForm.svelte";
</script>

<svelte:head><title>CAP - New question</title></svelte:head>

<AuthGuard let:user>
  <h2 class="h4 mb-3">
    <i class="fa-solid fa-circle-plus me-1"></i>File a new question
  </h2>
  {#if user.projects.length === 0}
    <div class="alert alert-warning">
      <i class="fa-solid fa-triangle-exclamation me-2"></i>
      Your session has no projects listed. You cannot file a question.
    </div>
  {:else}
    <QuestionForm mode="create" {user} />
  {/if}
</AuthGuard>
