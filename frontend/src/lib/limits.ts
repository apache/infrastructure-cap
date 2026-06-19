// Shared length limits. These mirror the constants in
// backend/cap_backend/schemas/common.py; keep the two in sync. The backend
// is the source of truth and re-checks every value, but the UI enforces the
// same bounds up front so a user never composes something the server rejects.

export const TITLE_MAX_LENGTH = 200;
export const TARGET_AUDIENCE_MAX_LENGTH = 200;
export const DESCRIPTION_MAX_LENGTH = 2500;
export const COMMENT_MAX_LENGTH = 2500;

// A stored comment longer than either of these bounds is collapsed behind a
// "Show more" toggle when displayed (see ExpandableComment.svelte). This is a
// display-only concern: the full text is always sent and stored, capped only
// by COMMENT_MAX_LENGTH above.
export const COMMENT_PREVIEW_MAX_CHARS = 500;
export const COMMENT_PREVIEW_MAX_LINES = 6;
