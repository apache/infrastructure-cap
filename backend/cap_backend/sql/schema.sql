-- CAP backend SQLite schema. Idempotent: every CREATE uses IF NOT EXISTS.
-- See SPEC.md section 7.

CREATE TABLE IF NOT EXISTS questions (
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
    is_binding           INTEGER NOT NULL
        CHECK (is_binding IN (0, 1)),
    is_private           INTEGER NOT NULL DEFAULT 0
        CHECK (is_private IN (0, 1)),
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

-- `request_id` has an implicit unique index from its UNIQUE constraint.
CREATE INDEX IF NOT EXISTS idx_questions_project_id ON questions(project_id);
CREATE INDEX IF NOT EXISTS idx_questions_status     ON questions(status);
CREATE INDEX IF NOT EXISTS idx_questions_closes_at  ON questions(closes_at);

CREATE TABLE IF NOT EXISTS responses (
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

CREATE INDEX IF NOT EXISTS idx_responses_question_id    ON responses(question_id);
CREATE INDEX IF NOT EXISTS idx_responses_question_voter ON responses(question_id, voter);
CREATE INDEX IF NOT EXISTS idx_responses_voter          ON responses(voter);
CREATE INDEX IF NOT EXISTS idx_responses_veto           ON responses(question_id, is_veto);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at  TEXT NOT NULL,
    actor        TEXT NOT NULL,
    action       TEXT NOT NULL
        CHECK (action IN (
            'question.create',
            'question.edit',
            'question.respond',
            'question.resolve',
            'question.remove'
        )),
    question_id  INTEGER,
    response_id  TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_audit_question_id ON audit_log(question_id);
CREATE INDEX IF NOT EXISTS idx_audit_actor       ON audit_log(actor);
CREATE INDEX IF NOT EXISTS idx_audit_action      ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_occurred_at ON audit_log(occurred_at);

-- Cursor used by the pubsub publisher (section 10.4).
CREATE TABLE IF NOT EXISTS pubsub_cursor (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    last_audit_id       INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO pubsub_cursor (id, last_audit_id) VALUES (1, 0);
