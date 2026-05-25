<script lang="ts">
  export let isPrivate: boolean;
</script>

{#if isPrivate}
  <span
    class="badge bg-warning text-dark"
    title="Private question - visible only to committee members and root"
  >
    <i class="fa-solid fa-lock me-1"></i>private
  </span>
{:else}
  <span class="badge bg-light text-secondary border" title="Public question">
    <i class="fa-solid fa-unlock me-1"></i>public
  </span>
{/if}
