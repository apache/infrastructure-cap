<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { ulid } from "ulid";
  import { push } from "svelte-spa-router";
  import type {
    ApprovalType,
    CreateQuestionRequest,
    EditQuestionRequest,
    Question,
    ResponseOption,
    UserSession,
  } from "../lib/types";
  import { api, ApiError } from "../lib/api";
  import { invalidateQuestion, pushToast } from "../lib/stores";
  import { isoToLocalInput, localInputToIso } from "../lib/time";
  import ProjectPicker from "./ProjectPicker.svelte";
  import ApprovalTypeSelector from "./ApprovalTypeSelector.svelte";
  import ResponseOptionEditor from "./ResponseOptionEditor.svelte";
  import ErrorAlert from "./ErrorAlert.svelte";

  export let mode: "create" | "edit";
  export let user: UserSession;
  export let question: Question | null = null;

  const dispatch = createEventDispatcher<{ saved: Question }>();

  function defaultClosesLocal(): string {
    const d = new Date(Date.now() + 7 * 86400 * 1000);
    return isoToLocalInput(d.toISOString());
  }

  function defaultResponseOption(at: ApprovalType): ResponseOption {
    if (at === "lazy_consensus")
      return { kind: "lazy_consensus", allow_comment: true };
    return {
      kind: "vote",
      allowed_values: ["+1", "+0", "-0", "-1"],
      allow_comment: true,
    };
  }

  let title = question?.title ?? "";
  let description = question?.description ?? "";
  let projectId =
    question?.project_id ?? (user.projects.length > 0 ? user.projects[0] : "");
  let targetAudience =
    question?.target_audience ??
    (projectId ? `Apache ${projectId} community` : "");
  let approvalType: ApprovalType =
    question?.approval_type ?? "majority_approval";
  let isBinding: boolean = question?.is_binding ?? true;
  let isPrivate: boolean = question?.is_private ?? false;
  let responseOption: ResponseOption =
    question?.response_option ?? defaultResponseOption(approvalType);
  let closesLocal =
    question != null ? isoToLocalInput(question.closes_at) : defaultClosesLocal();
  let requestId = question?.request_id ?? "";

  // When creating, the privacy checkbox is only enabled if the selected
  // project is in session.committees.
  $: canMarkPrivate =
    mode === "edit" ? true : user.committees.includes(projectId);
  $: if (!canMarkPrivate) isPrivate = isPrivate && false;

  let submitting = false;
  let errorMsg: string | null = null;

  function validate(): string | null {
    if (!title.trim()) return "Title is required.";
    if (title.length > 200) return "Title must be 200 characters or fewer.";
    if (!description.trim()) return "Description is required.";
    if (description.length > 10000)
      return "Description must be 10,000 characters or fewer.";
    if (!projectId) return "Choose a project.";
    if (!targetAudience.trim()) return "Target audience is required.";
    if (!closesLocal) return "Set a deadline.";
    const closesIso = localInputToIso(closesLocal);
    if (mode === "create" && Date.parse(closesIso) <= Date.now())
      return "Deadline must be in the future.";
    return null;
  }

  async function onSubmit() {
    errorMsg = validate();
    if (errorMsg) return;
    submitting = true;
    try {
      if (mode === "create") {
        const body: CreateQuestionRequest = {
          request_id: requestId || `req_${ulid()}`,
          project_id: projectId,
          title: title.trim(),
          description: description.trim(),
          target_audience: targetAudience.trim(),
          approval_type: approvalType,
          is_binding: isBinding,
          is_private: isPrivate,
          response_option: responseOption,
          closes_at: localInputToIso(closesLocal),
        };
        const created = await api.createQuestion(body);
        pushToast("success", `Question #${created.question_id} filed.`);
        dispatch("saved", created);
        push(`/question/${created.question_id}`);
      } else if (question) {
        const patch: EditQuestionRequest = {};
        if (title !== question.title) patch.title = title.trim();
        if (description !== question.description)
          patch.description = description.trim();
        if (targetAudience !== question.target_audience)
          patch.target_audience = targetAudience.trim();
        if (isPrivate !== question.is_private) patch.is_private = isPrivate;
        const closesIso = localInputToIso(closesLocal);
        if (closesIso !== question.closes_at) patch.closes_at = closesIso;
        if (
          JSON.stringify(responseOption) !==
          JSON.stringify(question.response_option)
        )
          patch.response_option = responseOption;

        const updated = await api.editQuestion(question.question_id, patch);
        invalidateQuestion(question.question_id);
        pushToast("success", `Question #${updated.question_id} updated.`);
        dispatch("saved", updated);
        push(`/question/${updated.question_id}`);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        errorMsg =
          err.body?.message ||
          err.body?.error ||
          `Request failed with status ${err.status}.`;
      } else {
        errorMsg = err instanceof Error ? err.message : "Submission failed.";
      }
    } finally {
      submitting = false;
    }
  }

  function onCancel() {
    if (mode === "edit" && question) {
      push(`/question/${question.question_id}`);
    } else {
      push("/");
    }
  }

  const editReadonly = mode === "edit";
</script>

<form class="card" on:submit|preventDefault={onSubmit}>
  <div class="card-body">
    {#if errorMsg}
      <ErrorAlert title="Could not save" message={errorMsg} />
    {/if}

    <div class="row g-3">
      <div class="col-12">
        <label class="form-label" for="q-title">Title</label>
        <input
          id="q-title"
          class="form-control"
          type="text"
          maxlength="200"
          bind:value={title}
          required
        />
        <div class="form-text">{title.length} / 200</div>
      </div>

      <div class="col-12">
        <label class="form-label" for="q-desc">Description</label>
        <textarea
          id="q-desc"
          class="form-control"
          rows="6"
          maxlength="10000"
          bind:value={description}
          required
        ></textarea>
        <div class="form-text">{description.length} / 10,000</div>
      </div>

      <div class="col-md-6">
        <label class="form-label" for="q-project">Project</label>
        <ProjectPicker
          id="q-project"
          bind:value={projectId}
          options={user.projects}
          disabled={editReadonly}
        />
        {#if editReadonly}
          <div class="form-text">Cannot be changed once the question is filed.</div>
        {/if}
      </div>

      <div class="col-md-6">
        <label class="form-label" for="q-audience">Target audience</label>
        <input
          id="q-audience"
          class="form-control"
          type="text"
          bind:value={targetAudience}
          required
        />
      </div>

      <div class="col-md-6">
        <label class="form-label" for="q-closes">Closes at (local time)</label>
        <input
          id="q-closes"
          class="form-control"
          type="datetime-local"
          bind:value={closesLocal}
          required
        />
        <div class="form-text">
          Sent to the server as UTC. Voters see a local-time countdown.
        </div>
      </div>

      <div class="col-md-6 d-flex flex-column">
        <div class="form-label">Flags</div>
        <div class="form-check form-switch">
          <input
            id="q-binding"
            class="form-check-input"
            type="checkbox"
            bind:checked={isBinding}
            disabled={editReadonly}
          />
          <label for="q-binding" class="form-check-label"
            >Distinguish binding votes</label
          >
        </div>
        {#if canMarkPrivate}
          <div class="form-check form-switch">
            <input
              id="q-private"
              class="form-check-input"
              type="checkbox"
              bind:checked={isPrivate}
            />
            <label for="q-private" class="form-check-label">
              <i class="fa-solid fa-lock me-1"></i>Private (committee only)
            </label>
          </div>
        {:else}
          <div class="form-text">
            Only members of <code>{projectId || "(no project)"}</code>'s committee
            may mark a question private.
          </div>
        {/if}
      </div>

      <div class="col-12">
        <div class="form-label">Approval type</div>
        <ApprovalTypeSelector bind:value={approvalType} disabled={editReadonly} />
        {#if editReadonly}
          <div class="form-text">Cannot be changed once the question is filed.</div>
        {/if}
      </div>

      <div class="col-12">
        <div class="form-label">Response options</div>
        <ResponseOptionEditor
          {approvalType}
          bind:value={responseOption}
        />
      </div>
    </div>
  </div>
  <div class="card-footer d-flex justify-content-between bg-white">
    <button type="button" class="btn btn-link" on:click={onCancel}>
      Cancel
    </button>
    <button class="btn btn-primary" type="submit" disabled={submitting}>
      {#if submitting}
        <i class="fa-solid fa-circle-notch fa-spin me-1"></i>
      {/if}
      {mode === "create" ? "File question" : "Save changes"}
    </button>
  </div>
</form>
