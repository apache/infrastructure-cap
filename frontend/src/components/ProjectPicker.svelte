<script lang="ts">
  import { projectDisplayName } from "../lib/projects";

  export let value: string = "";
  export let options: string[] = [];
  export let id: string = "project-picker";
  export let disabled: boolean = false;
</script>

<select
  class="form-select"
  {id}
  bind:value
  {disabled}
  required
>
  <option value="" disabled>Select a project...</option>
  {#each options as project}
    <option value={project}>{projectDisplayName(project)}</option>
  {/each}
</select>
