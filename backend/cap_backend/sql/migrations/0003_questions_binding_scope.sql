-- Migration 0003: replace questions.is_binding with questions.binding_scope.
--
-- The old boolean meant "distinguish binding votes", and a 0 meant *no* vote
-- counted as binding, which left every vote-counted question unwinnable. The
-- column becomes an explicit scope instead (SPEC §7.1, §7.2): 'committee'
-- (the default) means only PMC/PPMC members cast binding votes, 'project'
-- extends binding votes to every project member (committers included).
--
-- Every existing row lands on 'committee': that is both the new default and
-- what an old is_binding=1 question already meant, and it makes the old
-- is_binding=0 questions resolvable instead of permanently short of votes.
--
-- SQLite cannot ALTER a column's type or CHECK constraint, so `questions` is
-- rebuilt. `responses` is rebuilt straight afterwards for one reason: with
-- foreign keys enabled, `ALTER TABLE questions RENAME TO questions_old`
-- rewrites the child table's REFERENCES clause to point at questions_old, and
-- the later `DROP TABLE questions_old` would then perform an implicit
-- DELETE FROM that cascades away every response row. Re-pointing the child at
-- the new `questions` table first is what keeps the response history intact.
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
    is_private, permalink, status, outcome, closes_at, created_at, updated_at
)
SELECT question_id, request_id, project_id, title, description, requester,
       target_audience, approval_type, response_option_json, 'committee',
       is_private, permalink, status, outcome, closes_at, created_at, updated_at
  FROM questions_old;

-- Re-point the child table's REFERENCES clause at the new `questions` table.
-- `responses` has no children of its own, so dropping responses_old cascades
-- to nothing. Its own is_binding column is a per-vote snapshot (§7.2) and is
-- carried across untouched.
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
