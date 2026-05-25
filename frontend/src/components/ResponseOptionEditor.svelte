<script lang="ts">
  import type {
    ApprovalType,
    ResponseOption,
    VoteValue,
  } from "../lib/types";

  export let approvalType: ApprovalType;
  export let value: ResponseOption;

  const ALL_VALUES: VoteValue[] = ["+1", "+0", "-0", "-1"];
  let warning: string = "";

  function defaultFor(type: ApprovalType): ResponseOption {
    if (type === "lazy_consensus") {
      return { kind: "lazy_consensus", allow_comment: true };
    }
    return {
      kind: "vote",
      allowed_values: [...ALL_VALUES],
      allow_comment: true,
    };
  }

  function compatible(type: ApprovalType, kind: ResponseOption["kind"]): boolean {
    if (type === "lazy_consensus") return kind === "lazy_consensus";
    if (type === "unanimous_approval") return kind === "vote";
    return kind === "vote" || kind === "free_text";
  }

  $: if (!compatible(approvalType, value.kind)) {
    warning =
      "Approval type changed; response options reset to the default for this type.";
    value = defaultFor(approvalType);
  } else {
    warning = "";
  }

  // Extra constraint for unanimous_approval: must include "-1" and allow_comment.
  $: if (
    approvalType === "unanimous_approval" &&
    value.kind === "vote"
  ) {
    if (!value.allowed_values.includes("-1")) {
      value = {
        ...value,
        allowed_values: [...value.allowed_values, "-1"],
      };
    }
    if (!value.allow_comment) {
      value = { ...value, allow_comment: true };
    }
  }

  function toggleValue(v: VoteValue) {
    if (value.kind !== "vote") return;
    const has = value.allowed_values.includes(v);
    let next = has
      ? value.allowed_values.filter((x) => x !== v)
      : [...value.allowed_values, v];
    if (approvalType === "unanimous_approval" && !next.includes("-1")) {
      next = [...next, "-1"];
    }
    if (next.length === 0) next = [v];
    value = { ...value, allowed_values: next };
  }

  function setKind(newKind: ResponseOption["kind"]) {
    if (!compatible(approvalType, newKind)) return;
    if (newKind === value.kind) return;
    if (newKind === "vote") {
      value = {
        kind: "vote",
        allowed_values: [...ALL_VALUES],
        allow_comment: true,
      };
    } else if (newKind === "lazy_consensus") {
      value = { kind: "lazy_consensus", allow_comment: true };
    } else {
      value = { kind: "free_text", max_length: 4000 };
    }
  }

  function onKindChange(ev: Event) {
    const target = ev.currentTarget as HTMLSelectElement;
    setKind(target.value as ResponseOption["kind"]);
  }

  function setAllowComment(ev: Event) {
    const target = ev.currentTarget as HTMLInputElement;
    if (value.kind === "vote" || value.kind === "lazy_consensus") {
      value = { ...value, allow_comment: target.checked };
    }
  }

  function setMaxLength(ev: Event) {
    const target = ev.currentTarget as HTMLInputElement;
    const n = Number.parseInt(target.value, 10);
    if (value.kind === "free_text" && Number.isFinite(n)) {
      value = { ...value, max_length: n };
    }
  }

  $: kindOptions = (
    approvalType === "lazy_consensus"
      ? ["lazy_consensus"]
      : approvalType === "unanimous_approval"
        ? ["vote"]
        : ["vote", "free_text"]
  ) as ResponseOption["kind"][];
</script>

<div class="border rounded p-3 bg-white">
  {#if warning}
    <div class="alert alert-info py-2 mb-3 small">
      <i class="fa-solid fa-circle-info me-1"></i>{warning}
    </div>
  {/if}

  <div class="mb-3">
    <label class="form-label small text-muted" for="response-option-kind"
      >Response kind</label
    >
    <select
      id="response-option-kind"
      class="form-select"
      value={value.kind}
      on:change={onKindChange}
      disabled={kindOptions.length === 1}
    >
      {#each kindOptions as k}
        <option value={k}>
          {k === "vote"
            ? "Vote (+1 / +0 / -0 / -1)"
            : k === "lazy_consensus"
              ? "Lazy consensus (objection or silence)"
              : "Free text"}
        </option>
      {/each}
    </select>
  </div>

  {#if value.kind === "vote"}
    <div class="mb-2 small text-muted">Allowed values</div>
    <div class="d-flex flex-wrap gap-2 mb-3">
      {#each ALL_VALUES as v}
        <label class="form-check form-check-inline">
          <input
            class="form-check-input"
            type="checkbox"
            checked={value.allowed_values.includes(v)}
            on:change={() => toggleValue(v)}
            disabled={approvalType === "unanimous_approval" && v === "-1"}
          />
          <span class="form-check-label code-inline">{v}</span>
        </label>
      {/each}
    </div>
    <div class="form-check form-switch">
      <input
        id="vote-allow-comment"
        class="form-check-input"
        type="checkbox"
        checked={value.allow_comment}
        on:change={setAllowComment}
        disabled={approvalType === "unanimous_approval"}
      />
      <label for="vote-allow-comment" class="form-check-label">
        Allow optional comments
      </label>
    </div>
    {#if approvalType === "unanimous_approval"}
      <div class="form-text">
        Unanimous approval always permits -1 and requires comments (so veto
        reasons can be recorded).
      </div>
    {/if}
  {:else if value.kind === "lazy_consensus"}
    <div class="form-check form-switch">
      <input
        id="lazy-allow-comment"
        class="form-check-input"
        type="checkbox"
        checked={value.allow_comment}
        on:change={setAllowComment}
      />
      <label for="lazy-allow-comment" class="form-check-label">
        Allow optional comments
      </label>
    </div>
    <div class="form-text">
      Voters who do not object are recorded as silent assent.
    </div>
  {:else if value.kind === "free_text"}
    <div class="mb-2">
      <label for="free-max" class="form-label small text-muted"
        >Maximum length (characters)</label
      >
      <input
        id="free-max"
        type="number"
        class="form-control"
        min="1"
        max="10000"
        value={value.max_length}
        on:change={setMaxLength}
      />
    </div>
  {/if}
</div>
