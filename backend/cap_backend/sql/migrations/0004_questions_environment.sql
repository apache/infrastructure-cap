-- Migration 0004: add questions.environment.
--
-- `environment` controls where a question's email notifications go when the
-- server has `notifications.debug_recipient` configured (SPEC §7.1, §11.1):
-- 'default' honours the debug redirect, 'production' bypasses it and always
-- mails the project's own list. Only role-account tokens may file a question
-- with 'production' (SPEC §9.2); every existing row lands on 'default', which
-- is exactly how its notifications were routed before this column existed.
--
-- A plain `ALTER TABLE ... ADD COLUMN` would append the column after the
-- table-level CHECK in the stored CREATE statement, so the migrated schema
-- would no longer match the schema.sql snapshot. The table is rebuilt instead,
-- following the same pattern (and for the same foreign-key reason) as 0003:
-- renaming `questions` aside re-points `responses`' REFERENCES clause at
-- questions_old, so `responses` is rebuilt too before questions_old is
-- dropped, otherwise the drop would cascade away every response row.
--
-- The runner wraps this whole file in a single transaction, so either both
-- tables end up rebuilt or nothing changes.

ALTER TABLE questions RENAME TO questions_old;

CREATE TABLE questions (
    question_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id           TEXT NOT NULL UNIQUE,
    project_id           TEXT NOT NULL,
    title                TEXT NOT NULL,
    description          TEXT NOT NULL,
    requester            TEXT NOT NULL,
    target_audience      TEXT NOT NULL,
    approval_type        TEXT NOT NULL
        CHECK (approval_type IN (
            'unanimous_approval',
            'majority_approval',
            'simple_majority',
            'lazy_consensus'
        )),
    response_option_json TEXT NOT NULL,
    binding_scope        TEXT NOT NULL DEFAULT 'committee'
        CHECK (binding_scope IN ('committee', 'project')),
    is_private           INTEGER NOT NULL DEFAULT 0
        CHECK (is_private IN (0, 1)),
    environment          TEXT NOT NULL DEFAULT 'default'
        CHECK (environment IN ('default', 'production')),
    permalink            TEXT,
    status               TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'resolved', 'removed')),
    outcome              TEXT
        CHECK (outcome IS NULL OR outcome IN (
            'approved',
            'vetoed',
            'insufficient_votes',
            'withdrawn'
        )),
    closes_at            TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    CHECK ((status = 'open') = (outcome IS NULL))
);

INSERT INTO questions (
    question_id, request_id, project_id, title, description, requester,
    target_audience, approval_type, response_option_json, binding_scope,
    is_private, environment, permalink, status, outcome, closes_at, created_at,
    updated_at
)
SELECT question_id, request_id, project_id, title, description, requester,
       target_audience, approval_type, response_option_json, binding_scope,
       is_private, 'default', permalink, status, outcome, closes_at, created_at, updated_at
  FROM questions_old;

-- Re-point the child table's REFERENCES clause at the new `questions` table.
-- `responses` has no children of its own, so dropping responses_old cascades
-- to nothing. Its rows are carried across untouched.
ALTER TABLE responses RENAME TO responses_old;

CREATE TABLE responses (
    response_id    TEXT PRIMARY KEY,
    question_id    INTEGER NOT NULL
        REFERENCES questions(question_id) ON DELETE CASCADE,
    voter          TEXT NOT NULL,
    response_kind  TEXT NOT NULL
        CHECK (response_kind IN ('vote', 'lazy_consensus', 'free_text')),
    response_json  TEXT NOT NULL,
    comment        TEXT,
    is_binding     INTEGER NOT NULL DEFAULT 0
        CHECK (is_binding IN (0, 1)),
    is_veto        INTEGER NOT NULL DEFAULT 0
        CHECK (is_veto IN (0, 1)),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

INSERT INTO responses (
    response_id, question_id, voter, response_kind, response_json, comment,
    is_binding, is_veto, created_at, updated_at
)
SELECT response_id, question_id, voter, response_kind, response_json, comment,
       is_binding, is_veto, created_at, updated_at
  FROM responses_old;

DROP TABLE responses_old;
DROP TABLE questions_old;

-- Dropping the old tables also dropped their indexes (the names travelled with
-- the RENAME), so these CREATE statements reuse the original names.
CREATE INDEX IF NOT EXISTS idx_questions_project_id ON questions(project_id);
CREATE INDEX IF NOT EXISTS idx_questions_status     ON questions(status);
CREATE INDEX IF NOT EXISTS idx_questions_closes_at  ON questions(closes_at);

CREATE INDEX IF NOT EXISTS idx_responses_question_id    ON responses(question_id);
CREATE INDEX IF NOT EXISTS idx_responses_question_voter ON responses(question_id, voter);
CREATE INDEX IF NOT EXISTS idx_responses_voter          ON responses(voter);
CREATE INDEX IF NOT EXISTS idx_responses_veto           ON responses(question_id, is_veto);
