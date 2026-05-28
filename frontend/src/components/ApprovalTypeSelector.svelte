<script lang="ts">
  import type { ApprovalType } from "../lib/types";

  export let value: ApprovalType = "majority_approval";
  export let disabled: boolean = false;

  const options: {
    id: ApprovalType;
    label: string;
    description: string;
    icon: string;
  }[] = [
    {
      id: "unanimous_approval",
      label: "Unanimous approval",
      description:
        "Needs at least 3 binding +1 votes and no binding veto. Any binding -1 with a technical comment vetoes.",
      icon: "fa-solid fa-scale-balanced",
    },
    {
      id: "majority_approval",
      label: "Majority approval",
      description:
        "Needs at least 3 binding +1 votes, and binding +1 must outnumber binding -1 when the deadline elapses.",
      icon: "fa-solid fa-thumbs-up",
    },
    {
      id: "lazy_consensus",
      label: "Lazy consensus",
      description:
        "Silence is assent. The question passes unless someone objects before the deadline.",
      icon: "fa-solid fa-leaf",
    },
  ];
</script>

<div class="row g-2">
  {#each options as opt}
    <div class="col-md-4">
      <label
        class="approval-card d-block {value === opt.id ? 'selected' : ''}"
        class:disabled
      >
        <input
          type="radio"
          class="form-check-input visually-hidden"
          value={opt.id}
          bind:group={value}
          {disabled}
        />
        <div class="d-flex align-items-center gap-2 mb-1">
          <i class={opt.icon + " icon"}></i>
          <strong>{opt.label}</strong>
        </div>
        <div class="small text-muted">{opt.description}</div>
      </label>
    </div>
  {/each}
</div>
