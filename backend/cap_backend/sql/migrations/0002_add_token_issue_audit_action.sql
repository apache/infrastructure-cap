-- Migration 0002: allow the 'token.issue' action in audit_log.
--
-- GET /api/token now records a 'token.issue' audit row (SPEC §7.3, §9.12).
-- SQLite cannot ALTER an existing CHECK constraint, so the table is rebuilt:
-- rename the old table aside, create the new one with the widened CHECK, copy
-- every row across unchanged, drop the old table, and recreate the indexes.
--
-- The runner wraps this whole file in a single transaction, so the rebuild is
-- atomic: either the table ends up widened or nothing changes.

ALTER TABLE audit_log RENAME TO audit_log_old;

CREATE TABLE audit_log (
    audit_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at  TEXT NOT NULL,
    actor        TEXT NOT NULL,
    action       TEXT NOT NULL
        CHECK (action IN (
            'question.create',
            'question.edit',
            'question.respond',
            'question.resolve',
            'question.remove',
            'token.issue'
        )),
    question_id  INTEGER,
    response_id  TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);

INSERT INTO audit_log (
    audit_id, occurred_at, actor, action, question_id, response_id, details_json
)
SELECT audit_id, occurred_at, actor, action, question_id, response_id, details_json
  FROM audit_log_old;

-- Dropping the old table also drops its indexes (they kept their names through
-- the RENAME), so the CREATE INDEX statements below can reuse those names.
DROP TABLE audit_log_old;

CREATE INDEX IF NOT EXISTS idx_audit_question_id ON audit_log(question_id);
CREATE INDEX IF NOT EXISTS idx_audit_actor       ON audit_log(actor);
CREATE INDEX IF NOT EXISTS idx_audit_action      ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_occurred_at ON audit_log(occurred_at);
