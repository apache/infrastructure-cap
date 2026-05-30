<script lang="ts">
  import type { ApprovalType } from "../lib/types";

  export let value: ApprovalType = "majority_approval";
  export let disabled: boolean = false;

  const GLOSSARY_BASE = "https://www.apache.org/foundation/glossary";

  const options: {
    id: ApprovalType;
    label: string;
    description: string;
    icon: string;
    glossaryAnchor: string;
  }[] = [
    {
      id: "unanimous_approval",
      label: "Unanimous approval",
      description:
        "Needs at least 3 binding +1 votes and no binding veto. Any binding -1 with a technical comment vetoes.",
      icon: "fa-solid fa-scale-balanced",
      // The ASF glossary calls this "Consensus Approval".
      glossaryAnchor: "ConsensusApproval",
    },
    {
      id: "majority_approval",
      label: "Majority approval",
      description:
        "Needs at least 3 binding +1 votes, and binding +1 must outnumber binding -1 when the deadline elapses.",
      icon: "fa-solid fa-thumbs-up",
      glossaryAnchor: "MajorityApproval",
    },
    {
      id: "simple_majority",
      label: "Simple majority",
      description:
        "Passes when binding +1 strictly outnumbers binding -1. No minimum-three-votes floor: a single +1 with no -1 is enough.",
      icon: "fa-solid fa-arrow-up-9-1",
      glossaryAnchor: "SimpleMajority",
    },
    {
      id: "lazy_consensus",
      label: "Lazy consensus",
      description:
        "Silence is assent. The question passes unless someone objects before the deadline.",
      icon: "fa-solid fa-leaf",
      glossaryAnchor: "LazyConsensus",
    },
  ];
</script>

<div class="row g-2">
  {#each options as opt}
    <div class="col-md-6 col-lg-3">
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
        <div class="small mt-1">
          <a
            href="{GLOSSARY_BASE}#{opt.glossaryAnchor}"
            target="_blank"
            rel="noopener noreferrer"
            on:click|stopPropagation
            title="Open the ASF Foundation glossary entry for {opt.label} in a new tab"
          >
            <i class="fa-solid fa-book me-1"></i>ASF glossary
            <i class="fa-solid fa-up-right-from-square ms-1 small"></i>
          </a>
        </div>
      </label>
    </div>
  {/each}
</div>
