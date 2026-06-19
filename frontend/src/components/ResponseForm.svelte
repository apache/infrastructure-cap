<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import type {
    Question,
    StoredResponse,
    SubmittedResponse,
    VoteValue,
  } from "../lib/types";
  import {
    api,
    ApiError,
    RESPONSE_SUBMISSION_ENABLED,
  } from "../lib/api";
  import { pushToast } from "../lib/stores";
  import { COMMENT_MAX_LENGTH } from "../lib/limits";
  import ErrorAlert from "./ErrorAlert.svelte";

  export let question: Question;
  export let priorResponse: StoredResponse | null = null;

  const dispatch = createEventDispatcher<{ submitted: StoredResponse }>();

  let voteValue: VoteValue =
    (priorResponse?.response.kind === "vote"
      ? (priorResponse.response.value as VoteValue)
      : null) ?? "+1";
  let objection: boolean =
    priorResponse?.response.kind === "lazy_consensus"
      ? priorResponse.response.objection
      : false;
  let freeText: string =
    priorResponse?.response.kind === "free_text"
      ? priorResponse.response.text
      : "";
  let comment: string = priorResponse?.comment ?? "";

  let submitting = false;
  let errorMsg: string | null = null;
  let commentError: string | null = null;

  $: requiresVetoComment =
    question.approval_type === "unanimous_approval" &&
    question.response_option.kind === "vote" &&
    voteValue === "-1" &&
    question.viewer_is_binding;

  // Whether this question accepts a comment at all (vote / lazy_consensus
  // with allow_comment). free_text carries its own bounded body instead.
  $: commentEnabled =
    (question.response_option.kind === "vote" ||
      question.response_option.kind === "lazy_consensus") &&
    question.response_option.allow_comment;
  $: commentTooLong = comment.length > COMMENT_MAX_LENGTH;

  function buildBody(): SubmittedResponse | null {
    const ro = question.response_option;
    if (ro.kind === "vote" || ro.kind === "lazy_consensus") {
      if (ro.allow_comment && commentTooLong) {
        commentError = `Comment must be ${COMMENT_MAX_LENGTH.toLocaleString()} characters or fewer.`;
        return null;
      }
    }
    if (ro.kind === "vote") {
      if (requiresVetoComment && !comment.trim()) {
        commentError =
          "A non-empty comment is required when casting a binding -1 veto on a unanimous-approval question.";
        return null;
      }
      commentError = null;
      return {
        kind: "vote",
        value: voteValue,
        comment: ro.allow_comment ? comment.trim() || null : null,
      };
    }
    if (ro.kind === "lazy_consensus") {
      commentError = null;
      return {
        kind: "lazy_consensus",
        objection,
        comment: ro.allow_comment ? comment.trim() || null : null,
      };
    }
    return { kind: "free_text", text: freeText };
  }

  async function onSubmit() {
    if (!RESPONSE_SUBMISSION_ENABLED) {
      errorMsg = "Response submission is not yet enabled on this server.";
      return;
    }
    const body = buildBody();
    if (!body) return;
    submitting = true;
    errorMsg = null;
    try {
      const r = await api.submitResponse(question.question_id, body);
      pushToast("success", "Response recorded.");
      dispatch("submitted", r);
    } catch (err) {
      if (err instanceof ApiError) {
        errorMsg =
          err.body?.message ||
          err.body?.error ||
          `Submission failed (HTTP ${err.status}).`;
      } else {
        errorMsg = err instanceof Error ? err.message : "Submission failed.";
      }
    } finally {
      submitting = false;
    }
  }

  $: submitDisabled =
    submitting ||
    !RESPONSE_SUBMISSION_ENABLED ||
    (commentEnabled && commentTooLong);
  $: submitLabel = priorResponse ? "Update response" : "Submit response";
</script>

<form class="card" on:submit|preventDefault={onSubmit}>
  <div class="card-body">
    {#if !RESPONSE_SUBMISSION_ENABLED}
      <div class="alert alert-info py-2 small">
        <i class="fa-solid fa-circle-info me-1"></i>
        Response submission is currently disabled on this client.
      </div>
    {/if}
    {#if errorMsg}
      <ErrorAlert title="Could not submit response" message={errorMsg} />
    {/if}

    {#if question.response_option.kind === "vote"}
      <fieldset class="mb-3">
        <legend class="form-label">Your vote</legend>
        <div class="d-flex flex-wrap gap-3">
          {#each question.response_option.allowed_values as v}
            <label class="form-check">
              <input
                type="radio"
                class="form-check-input"
                value={v}
                bind:group={voteValue}
              />
              <span class="form-check-label code-inline">{v}</span>
            </label>
          {/each}
        </div>
      </fieldset>
      {#if question.response_option.allow_comment}
        <div class="mb-3">
          <label class="form-label" for="resp-comment">
            Comment
            {#if requiresVetoComment}
              <span class="text-danger">(required for binding -1 veto)</span>
            {:else}
              <span class="text-muted">(optional)</span>
            {/if}
          </label>
          <textarea
            id="resp-comment"
            class="form-control"
            class:is-invalid={commentError || commentTooLong}
            rows="4"
            maxlength={COMMENT_MAX_LENGTH}
            bind:value={comment}
          ></textarea>
          {#if commentError}
            <div class="invalid-feedback">{commentError}</div>
          {/if}
          <div
            class="form-text text-end"
            class:text-danger={commentTooLong}
          >
            {comment.length.toLocaleString()} / {COMMENT_MAX_LENGTH.toLocaleString()}
          </div>
        </div>
      {/if}
    {:else if question.response_option.kind === "lazy_consensus"}
      <div class="form-check mb-3">
        <input
          id="resp-objection"
          class="form-check-input"
          type="checkbox"
          bind:checked={objection}
        />
        <label class="form-check-label" for="resp-objection">
          I object to this proposal.
        </label>
        <div class="form-text">
          Silence is assent. Submit with this box checked only if you object.
        </div>
      </div>
      {#if question.response_option.allow_comment}
        <div class="mb-3">
          <label class="form-label" for="resp-lc-comment"
            >Comment <span class="text-muted">(optional)</span></label
          >
          <textarea
            id="resp-lc-comment"
            class="form-control"
            class:is-invalid={commentTooLong}
            rows="4"
            maxlength={COMMENT_MAX_LENGTH}
            bind:value={comment}
          ></textarea>
          <div
            class="form-text text-end"
            class:text-danger={commentTooLong}
          >
            {comment.length.toLocaleString()} / {COMMENT_MAX_LENGTH.toLocaleString()}
          </div>
        </div>
      {/if}
    {:else if question.response_option.kind === "free_text"}
      <div class="mb-3">
        <label class="form-label" for="resp-text">Your response</label>
        <textarea
          id="resp-text"
          class="form-control"
          rows="6"
          maxlength={question.response_option.max_length}
          bind:value={freeText}
        ></textarea>
        <div class="form-text">
          {freeText.length} / {question.response_option.max_length}
        </div>
      </div>
    {/if}
  </div>
  <div class="card-footer bg-white d-flex justify-content-end">
    <button class="btn btn-primary" type="submit" disabled={submitDisabled}>
      {#if submitting}
        <i class="fa-solid fa-circle-notch fa-spin me-1"></i>
      {:else}
        <i class="fa-solid fa-paper-plane me-1"></i>
      {/if}
      {submitLabel}
    </button>
  </div>
</form>
