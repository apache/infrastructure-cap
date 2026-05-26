# CAP Backend Specification

This document specifies the Python backend server for the ASF Infra
Contingent Approval Provider (CAP). It complements the high-level service
description in [`../README.md`](../README.md) by defining the concrete
runtime, framework, schema, and endpoint contracts for the initial
iteration of the service.

## 1. Goals and Scope

The backend is a small HTTP service that accepts and serves contingent
approval workflows on behalf of ASF projects. The current iteration
covers:

1. Bootstrapping a runnable [`asfquart`](https://github.com/apache/infrastructure-asfquart)
   application with OAuth-protected endpoints, an integrated `quart-schema`
   OpenAPI surface, and the response normalizer described in section 3.1.
2. Defining a typed schema (via Pydantic) for questions, responses, errors,
   and the resolution permalink record.
3. Exposing the following endpoints:
   - `GET /api` — the auto-generated OpenAPI specification for the entire
     HTTP API. Public (no auth).
   - `GET /docs` — a Swagger UI HTML page that renders the `/api`
     document for interactive browsing. Public (no auth).
   - `GET /list` — the list of pending questions visible to the currently
     authenticated user.
   - `POST /question` — create a new question.
   - `GET /question/{id}` — fetch a single question and all of its
     recorded responses.
   - `PATCH /question/{id}` — edit a question's metadata while it is
     still open.
   - `DELETE /question/{id}` — withdraw a question before it resolves.
   - `POST /question/{id}/resolve` — finalize a question, run the tally,
     and issue its permalink.
   - `POST /question/{id}/responses` — submit a new response, or amend
     the caller's previous response.
4. Recording every state-changing action in an append-only audit log
   inside the same SQLite transaction that performed the write
   (section 7.3).
5. Broadcasting every state-changing action to the project's mailing
   list via `asfpy.messaging.mail` (section 11). Private questions
   route to `private@{project}.apache.org`; public questions route to
   `dev@{project}.apache.org`.

The remaining CAP workflow endpoint (`GET /resolution/{id}`, the
permalink endpoint in section 9.8) is specified but not yet
implemented. The Pydantic schema layer and audit-log discipline
already accommodate it.

## 2. Technology Stack

| Concern              | Choice                                                       |
|----------------------|--------------------------------------------------------------|
| Language             | Python 3.12+                                                 |
| Environment / deps   | [`uv`](https://docs.astral.sh/uv/) (lockfile and virtualenv) |
| Web framework        | `asfquart` (Quart-based, ASF OAuth integration)              |
| Schema / validation  | `pydantic` v2                                                |
| OpenAPI integration  | `quart-schema` (Pydantic-aware OpenAPI generation)           |
| Server binding       | Plain HTTP on `0.0.0.0:8085` (TLS terminates upstream)       |
| Auth                 | ASF OAuth via `asfquart.auth`                                |
| Persistence          | SQLite 3 (stdlib `sqlite3`), file path from `config.yaml`    |
| Config file format   | YAML (via `pyyaml`), loaded at startup                       |
| Pubsub               | `pypubsub` over HTTP POST (section 10)                       |
| Email notifications  | `asfpy.messaging.mail` to project mailing lists (section 11) |

`quart-schema` is chosen because it consumes Pydantic models directly,
produces an OpenAPI 3.x document from registered routes, and integrates
cleanly with `asfquart` (which is a thin layer over Quart). The first
iteration uses `quart-schema`; hand-rolling the OpenAPI assembly is
explicitly out of scope.

## 3. Project Layout

```
backend/
├── pyproject.toml              # uv-managed project metadata + deps
├── uv.lock                     # uv lockfile (committed)
├── config.yaml                 # runtime config (example/dev copy)
├── README.md                   # operator notes (how to run, dev tips)
├── SPEC.md                     # this document
└── cap_backend/
    ├── __init__.py             # package marker; re-exports `build_app`
    │                           # from `cap_backend.app`. No module-level
    │                           # app instance is created at import time.
    ├── __main__.py             # `python -m cap_backend` entrypoint
    ├── app.py                  # defines `build_app() -> QuartApp`:
    │                           # asfquart construct + blueprint wiring +
    │                           # ClientSession response normalizer
    │                           # (section 3.1)
    ├── auth.py                 # OAuth helpers, "require login" hook,
    │                           # `AuthenticatedUser` dataclass,
    │                           # `can_view_question` ACL helper
    ├── config.py               # Pydantic settings loaded from config.yaml
    ├── db.py                   # SQLite connection + schema bootstrap
    ├── dao.py                  # row <-> Pydantic projection, INSERT/
    │                           # UPDATE helpers for `questions` and
    │                           # `responses` (caller owns the txn)
    ├── tally.py                # pure resolve-time tally rules per
    │                           # approval_type (section 9.6)
    ├── audit.py                # audit-log helpers (write-only API)
    ├── notify.py               # email notifications via
    │                           # `asfpy.messaging.mail` (section 11)
    ├── pubsub.py               # background publisher that tails
    │                           # audit_log and POSTs events to a
    │                           # pypubsub instance (section 10)
    ├── openapi.py              # /api endpoint (OpenAPI document) and
    │                           # /docs endpoint (Swagger UI HTML)
    ├── routes/
    │   ├── __init__.py
    │   └── questions.py        # all `/list`, `/question/*`,
    │                           # `/question/<id>/resolve` and
    │                           # `/question/<id>/responses` handlers
    ├── schemas/
    │   ├── __init__.py
    │   ├── common.py           # shared primitives (ASF UID, timestamps)
    │   ├── errors.py           # `AuthenticationRequired`, `ErrorMessage`
    │   ├── responses.py        # response-option schemas (dynamic)
    │   └── questions.py        # Question, ListResponse, QuestionDetail,
    │                           # CreateQuestionRequest, EditQuestionRequest,
    │                           # ResolutionRecord
    └── sql/
        └── schema.sql          # CREATE TABLE statements for SQLite
```

### 3.1 Integration notes

Two integration points were not obvious from the section headings above
and are documented here so future iterations don't have to rediscover
them:

1. **Response model decorators are mandatory for the OpenAPI document.**
   `quart-schema` builds the `paths.<route>.responses` and
   `components.schemas` blocks of `/api` by introspecting the route
   handlers. Every CAP route therefore wears the appropriate
   `@validate_request(...)`, `@validate_response(Model, status)` and
   `@document_response(ErrorModel, status)` decorators from
   `quart_schema`; a route that returns `jsonify(...)` without these
   decorators is functionally correct but shows up in `/api` as an
   undocumented endpoint (empty `responses`, no referenced schemas).
2. **`asfquart`'s `/auth` returns a `ClientSession` (a `dict`
   subclass) directly when the caller is logged in.** `quart-schema`'s
   response converter dispatches dict-like return values through
   `pydantic.TypeAdapter(type(value)).dump_python(value)`, which then
   fails on a `ClientSession` with `PydanticSchemaGenerationError`.
   `cap_backend/app.py` installs a `make_response` wrapper
   (`_install_response_normalizer`) that runs *after* `quart-schema`
   has wrapped `app.make_response`, so it sees the route's return
   value first, downgrades any `ClientSession` (bare or tuple-shaped)
   into a plain `dict`, and hands the normalized payload to
   `quart-schema`'s converter. The wire format is unchanged; only the
   intermediate type is rewritten.

## 4. Environment and Dependency Management

The project is managed with `uv`. The `pyproject.toml` declares
runtime dependencies and a `[project.scripts]` entry point:

```toml
[project]
name = "cap-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "asfquart",
  "quart-schema[pydantic]",
  "pydantic>=2.6",
]

[project.scripts]
cap-backend = "cap_backend.__main__:main"
```

Typical operator commands:

```bash
# install / sync deps into .venv
uv sync

# run the server in development
uv run cap-backend

# regenerate the lockfile
uv lock
```

## 5. Runtime Configuration

The server binds to `0.0.0.0:8085` and serves plain HTTP. TLS is
expected to be terminated by an upstream reverse proxy (e.g. the public
`cap.apache.org` ingress). The entrypoint is roughly:

```python
# cap_backend/__main__.py
from cap_backend.app import build_app

def main() -> None:
    app = build_app()
    app.runx(host="0.0.0.0", port=8085)

if __name__ == "__main__":
    main()
```

### 5.1 `config.yaml`

Runtime configuration is loaded from a YAML file at startup. The file
path is resolved in this order:

1. `--config <path>` CLI argument, if given.
2. `CAP_CONFIG` environment variable, if set.
3. `./config.yaml` in the working directory.
4. `/etc/cap/config.yaml`.

Example `config.yaml`:

```yaml
server:
  host: "0.0.0.0"
  port: 8085
  # Base URL prepended to issued permalinks (section 9.6 / 9.8).
  # Empty string yields bare paths like "/resolution/4217" (useful in
  # dev); production should set this to the public host, e.g.
  # "https://cap.apache.org".
  permalink_base: ""

database:
  # Absolute or relative path to the SQLite file. The parent directory
  # must exist and be writable by the server process.
  path: "/var/lib/cap/cap.sqlite3"

oauth:
  # Optional override for the asfquart OAuth gateway base URL.
  base_url: null

pubsub:
  # Set to false to disable outbound publishing (e.g. in dev/test).
  enabled: true
  # Base URL of a pypubsub instance (https://github.com/humbedooh/pypubsub).
  # Events are POSTed to <base_url>/question/<type>/<project>/<id>,
  # or <base_url>/private/question/<type>/<project>/<id> for questions
  # whose `is_private` flag is true.
  base_url: "https://pubsub.apache.org:2069"
  # HTTP basic auth credentials for posting to private topics. Optional;
  # if omitted the publisher will only post to public topics and will
  # log a WARNING when it skips a private event.
  basic_auth:
    username: "cap-publisher"
    password: null      # may also be provided via CAP_PUBSUB_PASSWORD
  # Per-request timeout (connect + read) when POSTing to pypubsub.
  timeout_seconds: 5

logging:
  level: "INFO"
```

A small Pydantic settings model (`cap_backend/config.py`) parses and
validates this file. Unknown keys are rejected (`extra="forbid"`) so
typos cannot silently disable features.

## 6. Authentication

All endpoints require an authenticated ASF user. This is enforced
globally, not per-route, so that no future endpoint can be added
without authentication by accident.

Enforcement strategy:

1. The OAuth gateway provided by `asfquart` (mounted at `/auth` by
   `asfquart.construct(...)`) is left at its default mount point and
   is unauthenticated (it has to be, in order to perform the login
   handshake). `GET /api` is also exempt, so the OpenAPI specification
   can be consumed by external tooling without an ASF account, as is
   `GET /docs`, the Swagger UI page that renders it (section 9.10).
   These are the only unauthenticated paths; every other route,
   including any added in the future, requires login by default.
2. A `before_request` hook in `cap_backend/auth.py`
   (`require_authentication`) inspects the session for an authenticated
   ASF user. If absent, the hook:
   - For browser-style requests (Accept includes `text/html`): redirects
     to the OAuth gateway with a `redirect` query param pointing back
     at the original URL.
   - For API-style requests (Accept includes `application/json`, or no
     `Accept` header is supplied — JSON is the API-server default):
     returns `401 Unauthorized` with a JSON body
     `{"error": "authentication_required", "login_url": "/auth?..."}`.
   The body matches the `AuthenticationRequired` Pydantic model in
   `cap_backend/schemas/errors.py`; every authenticated route declares
   the same 401 shape via `@document_response(AuthenticationRequired,
   401)` so the OpenAPI document is self-describing.
3. The authenticated user is exposed to handlers as a frozen dataclass
   (`AuthenticatedUser`) loaded from the asfquart session, carrying:

   | field        | type            | source                              |
   |--------------|-----------------|-------------------------------------|
   | `uid`        | `str`           | `asfquart.session.uid`              |
   | `committees` | `tuple[str,…]`  | `asfquart.session.committees`       |
   | `is_root`    | `bool`          | `asfquart.session.isRoot`           |
   | `fullname`   | `str \| None`   | `asfquart.session.fullname`         |
   | `extras`     | `dict[str,Any]` | reserved for future session fields  |

   Handlers retrieve the user via `await current_user()` rather than
   touching the session directly. The `committees` tuple is what
   determines binding eligibility when a response is submitted (see
   section 7.2) and gates `POST /question` on the caller's project
   membership (see section 9.2).

Authorization beyond "logged in" is layered on per route:

- Standard endpoints (e.g. `/list`) require only that the global hook
  has accepted the request.
- Administrative endpoints (see section 9.11) additionally require
  `session.isRoot`, declared via the asfquart decorator
  `@asfquart.auth.require(R.root)`.

The OpenAPI document served from `GET /api` is intentionally public,
so external integrators can introspect the API without going through
the OAuth flow. The document itself declares the OAuth security
requirement on every other endpoint, so it is self-describing about
which routes need login.

## 7. Persistence (SQLite)

The service uses a single SQLite 3 database file, opened via the
stdlib `sqlite3` module. The file path is taken from `database.path`
in `config.yaml` (see section 5.1). The database is opened with:

- `PRAGMA journal_mode = WAL;` (concurrent readers, one writer).
- `PRAGMA foreign_keys = ON;`
- `PRAGMA synchronous = NORMAL;`
- A single shared connection serialized through an `asyncio.Lock` for
  writes; reads may use short-lived per-request connections. (SQLite
  in WAL mode tolerates concurrent reads with a single writer.)

On startup, `cap_backend/db.py` runs the statements in
`cap_backend/sql/schema.sql` with `CREATE TABLE IF NOT EXISTS`, so the
schema is materialized on first launch and is a no-op on subsequent
starts. Future migrations will live in numbered files (`0001_*.sql`,
`0002_*.sql`, ...) tracked by a `schema_migrations` table; that
migration runner is not part of this iteration but the layout reserves
room for it.

All three tables share two common timestamp columns: `created_at` and
`updated_at`, both stored as ISO 8601 UTC text (`TEXT NOT NULL`). This
keeps timestamps human-readable in `sqlite3` CLI dumps and survives
backup/restore without a binary timezone dance.

### 7.1 Table: `questions`

Mirrors the `Question` Pydantic class from section 8.3. Fields with a
fixed shape become columns; the polymorphic `response_option` (a
discriminated union) is stored as a JSON blob in a single column,
keeping the column count stable as new response kinds are added.

```sql
CREATE TABLE IF NOT EXISTS questions (
    question_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                                                      -- numerical, monotonic,
                                                      -- globally unique;
                                                      -- server-assigned on
                                                      -- INSERT (clients MUST
                                                      -- NOT supply it);
                                                      -- used in the pubsub URL
    request_id           TEXT NOT NULL UNIQUE,        -- RequestID; MUST be
                                                      -- globally unique across
                                                      -- the questions table
                                                      -- and is server-assigned
                                                      -- on INSERT (clients MUST
                                                      -- NOT supply it).
    project_id           TEXT NOT NULL,               -- ASF project id, matched
                                                      -- against session.committees
    title                TEXT NOT NULL,
    description          TEXT NOT NULL,
    requester            TEXT NOT NULL,               -- ASFUserID
    target_audience      TEXT NOT NULL,
    approval_type        TEXT NOT NULL
        CHECK (approval_type IN (
            'unanimous_approval',
            'majority_approval',
            'lazy_consensus'
        )),
    response_option_json TEXT NOT NULL,               -- JSON: ResponseOption
    is_binding           INTEGER NOT NULL
        CHECK (is_binding IN (0, 1)),                 -- whether the question
                                                      -- distinguishes binding votes
    is_private           INTEGER NOT NULL DEFAULT 0
        CHECK (is_private IN (0, 1)),                 -- routes pubsub events
                                                      -- through the private topic
    permalink            TEXT,                        -- NULL until resolved
    status               TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'resolved', 'removed')),
    outcome              TEXT
        CHECK (outcome IS NULL OR outcome IN (
            'approved',
            'vetoed',
            'insufficient_votes',
            'withdrawn'
        )),
    closes_at            TEXT NOT NULL,               -- ISO-8601 UTC
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,

    -- outcome is NULL exactly when status = 'open'
    CHECK ((status = 'open') = (outcome IS NULL))
);

-- `request_id` already has an implicit unique index from its UNIQUE
-- constraint above, so no separate index is created here.
CREATE INDEX IF NOT EXISTS idx_questions_project_id ON questions(project_id);
CREATE INDEX IF NOT EXISTS idx_questions_status     ON questions(status);
CREATE INDEX IF NOT EXISTS idx_questions_closes_at  ON questions(closes_at);
```

`question_id` is declared `INTEGER PRIMARY KEY AUTOINCREMENT` so the
server can hand out a monotonically increasing numerical id (1, 2,
3, ...) that is safe to expose in the pubsub URL (see section 10).
SQLite's `AUTOINCREMENT` keyword (rather than the default implicit
rowid alias) is used deliberately because pubsub consumers may use
`question_id` as a stable cursor, and we must not reuse ids even
after a question is removed. `question_id` is always assigned by
the server on INSERT; clients cannot pre-allocate or supply one.

`request_id` carries a `UNIQUE` constraint at the SQL level, so two
questions may never share the same `request_id`. The intent is that
each request maps to exactly one question row. `request_id` is
allocated by the server when the row is inserted (a fresh ULID/UUID,
generated alongside the `AUTOINCREMENT` `question_id`); clients MUST
NOT supply or pre-allocate a `request_id`. The value is a stable
external identifier for the request and is the string used in any
external reference that needs to be opaque (whereas `question_id` is
the numerical id used in pubsub URLs).

The row-to-Pydantic mapping is:

| Column                 | Pydantic field           |
|------------------------|--------------------------|
| `question_id`          | `question_id`            |
| `request_id`           | `request_id`             |
| `project_id`           | `project_id`             |
| `title`                | `title`                  |
| `description`          | `description`            |
| `requester`            | `requester`              |
| `target_audience`      | `target_audience`        |
| `approval_type`        | `approval_type`          |
| `response_option_json` | `response_option` (JSON) |
| `is_binding`           | `is_binding`             |
| `is_private`           | `is_private`             |
| `permalink`            | `permalink`              |
| `status`               | `status`                 |
| `outcome`              | `outcome`                |
| `closes_at`            | `closes_at`              |
| `created_at`           | `created_at`             |

`updated_at` is a persistence-only column (not surfaced on the API
model) used by the resolver and the audit log. The
`viewer_is_binding` and `time_remaining_seconds` fields on the
`Question` Pydantic model are server-computed per response and are
deliberately not stored on this table.

### 7.2 Table: `responses`

Holds one row per submitted response. A voter may amend their response
while the question is open; the table preserves history by appending a
new row each time (queries pick the latest per `(question_id, voter)`
using `MAX(created_at)`), and the audit log captures the same event.
The polymorphic submitted payload is stored as JSON for the same
reason `response_option_json` is on `questions`.

```sql
CREATE TABLE IF NOT EXISTS responses (
    response_id    TEXT PRIMARY KEY,                  -- ULID/UUID; globally
                                                      -- unique and server-
                                                      -- assigned on INSERT
                                                      -- (clients MUST NOT
                                                      -- supply it).
    question_id    TEXT NOT NULL
        REFERENCES questions(question_id) ON DELETE CASCADE,
    voter          TEXT NOT NULL,                     -- ASFUserID
    response_kind  TEXT NOT NULL
        CHECK (response_kind IN ('vote', 'lazy_consensus', 'free_text')),
    response_json  TEXT NOT NULL,                     -- JSON: SubmittedResponse
    comment        TEXT,                              -- denormalized for search
    is_binding     INTEGER NOT NULL DEFAULT 0
        CHECK (is_binding IN (0, 1)),                 -- snapshot: this voter
                                                      -- was binding for THIS vote
    is_veto        INTEGER NOT NULL DEFAULT 0
        CHECK (is_veto IN (0, 1)),                    -- set only for vetoes on
                                                      -- unanimous_approval questions
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_responses_question_id      ON responses(question_id);
CREATE INDEX IF NOT EXISTS idx_responses_question_voter   ON responses(question_id, voter);
CREATE INDEX IF NOT EXISTS idx_responses_voter            ON responses(voter);
CREATE INDEX IF NOT EXISTS idx_responses_veto             ON responses(question_id, is_veto);
```

`is_binding` is captured at submission time (and not derived later)
because a voter's committee membership at the moment of voting is
what the tally must reference, even if their membership changes
afterwards. The value is computed by the response handler as:

```
is_binding = question.is_binding AND (question.project_id in session.committees)
```

If `question.is_binding` is false the vote is recorded as
non-binding regardless of committee membership; if true, only voters
whose `asfquart.session.committees` includes `question.project_id`
get a binding vote, and everyone else's submission is recorded as
non-binding. `session.committees` is consulted exactly once, at the
moment the response is written, and the result is frozen in this
column.

`is_veto` is also a denormalized snapshot. It is set to `1` only when
all of the following hold at submission time:

- `question.approval_type == 'unanimous_approval'`
- The submitted response is a `vote` with `value == '-1'`
- `is_binding` (above) evaluates to `1`
- The submission carries a non-empty `comment` (the technical reason)

The dedicated index on `(question_id, is_veto)` lets the resolver
short-circuit the unanimous-approval tally with a single index lookup
("does this question have any vetoes?").

### 7.3 Table: `audit_log`

Append-only log of every state-changing action. Rows are never updated
or deleted. Each row records *who* did *what* to *which* question, and
a JSON `details` blob carries action-specific context (the before/after
diff for an edit, the response body for a submission, etc).

The actions tracked are exactly the ones called out in this spec:

- `question.create`: a new question (and its parent request) is recorded.
- `question.edit`: a question's metadata is changed before it resolves.
- `question.respond`: a voter submits or amends a response.
- `question.resolve`: the voting window closes and a permalink is issued.
- `question.remove`: a question is withdrawn before resolving.

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at  TEXT NOT NULL,                       -- ISO-8601 UTC
    actor        TEXT NOT NULL,                       -- ASFUserID; 'system' for automated
    action       TEXT NOT NULL
        CHECK (action IN (
            'question.create',
            'question.edit',
            'question.respond',
            'question.resolve',
            'question.remove'
        )),
    question_id  INTEGER,                             -- nullable for future non-question actions
    response_id  TEXT,                                -- set for question.respond
    details_json TEXT NOT NULL DEFAULT '{}'           -- action-specific payload
);

CREATE INDEX IF NOT EXISTS idx_audit_question_id ON audit_log(question_id);
CREATE INDEX IF NOT EXISTS idx_audit_actor       ON audit_log(actor);
CREATE INDEX IF NOT EXISTS idx_audit_action      ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_occurred_at ON audit_log(occurred_at);
```

There are no foreign keys from `audit_log` to `questions` or
`responses`. The audit log must survive even if a question is later
removed, so referential integrity is intentionally not enforced; the
`question_id` and `response_id` columns are opaque references.

**Retention.** The audit log is retained indefinitely. There is no
TTL, no archival job, and no pruning policy in this iteration. Every
row written to `audit_log` is expected to live for the lifetime of
the database. Operators who need to bound disk usage should plan to
move the SQLite file onto storage sized for unbounded growth rather
than to delete rows.

Write discipline:

- Every state-changing handler MUST wrap its write and its audit
  insertion in the same SQLite transaction. The helper
  `audit.record(action, actor, question_id=..., response_id=..., details=...)`
  in `cap_backend/audit.py` takes the active connection and performs
  the insert; callers must not log to `audit_log` outside a
  transactional path.
- The audit log is the source of truth that feeds the internal
  pubsub stream (section 10). The pubsub publisher tails this table
  by `audit_id`.

### 7.4 Lifecycle and ordering rules

Because the service is asynchronous (responses arrive concurrently
with the resolver loop and the creator's edit/remove actions), the
rules below are the **canonical, in-order** checks every
state-changing handler MUST apply. They are evaluated against the
server's clock and the question's row as observed inside the
handler's SQLite transaction, never against any value supplied by
the client.

**Acceptance order for a new response on question `q`:**

1. **Deadline check.** If `now_utc() >= q.closes_at`, the response
   is rejected with `409 Conflict`. The deadline is absolute: once
   it has passed, no further responses are accepted, including any
   that were already in the event loop's pending queue when the
   deadline elapsed. The audit log records no entry for a
   deadline-rejected response.
2. **Status check.** Otherwise, if `q.status != 'open'` (i.e. the
   creator or root has already resolved or removed the question),
   the response is rejected with `409 Conflict`. This covers the
   "creator closed the question before the deadline" case and the
   "creator resolved early because consensus was reached" case.
3. Otherwise, the response is accepted and persisted (section 9.7).

This ordering means a question can become unwriteable for two
distinct reasons, and the deadline always wins ties: a response
that arrives at the exact instant `closes_at` is reached is
rejected by step 1 even if the creator simultaneously attempts to
resolve. The resolver loop applies the same ordering: when
`closes_at` is reached it first stops accepting responses, then
runs the tally on the frozen response set.

**Acceptance order for `POST /question/{id}/resolve`:**

1. If `q.status != 'open'`, return the existing resolved record
   (idempotent, see section 9.6).
2. Otherwise, run the tally against the responses currently in the
   database (the deadline check above guarantees this set is final
   if `now_utc() >= q.closes_at`).
3. Set `q.status = 'resolved'`, populate `q.outcome` and
   `q.permalink`, bump `q.updated_at`, write the `question.resolve`
   audit row, all in one transaction.

**Acceptance order for `DELETE /question/{id}` (creator-initiated
removal):**

1. If `q.status != 'open'`, return `409 Conflict`.
2. Otherwise set `q.status = 'removed'` and `q.outcome = 'withdrawn'`,
   bump `q.updated_at`, write the `question.remove` audit row, all
   in one transaction.

### 7.5 View-access ACL for private questions

Every endpoint that surfaces question data (`/list`,
`GET /question/{id}`, `GET /resolution/{id}`) consults a single
helper, `auth.can_view_question(user, question) -> bool`, before
returning a row. The helper's rule is:

- If `question.is_private == False`: return `True` for any
  authenticated user.
- If `question.is_private == True`: return `True` if **any** of
  the following hold for `user`:
  - `user.is_root` is true (i.e. `session.isRoot`).
  - `question.project_id` appears in `user.committees`.
  - `'tooling'` appears in `user.committees`. The `tooling`
    committee is granted blanket private-question read access so
    that infrastructure automation written by that team can
    introspect any CAP question without per-project credentials.
- Otherwise: return `False`.

Handlers that observe `can_view_question(...) == False` return
**`404 Not Found`**, never `403 Forbidden`. This is deliberate: a
`403` would disclose that a private question with that
`question_id` exists. `404` makes private questions indistinguishable
from never-existed questions for unauthorized viewers.

`/list` applies the same helper as a `WHERE` predicate, so private
questions the caller cannot view are silently filtered out of the
returned `pending` array. The same goes for `GET /resolution/{id}`:
the 404 case covers both "no such id" and "id exists but ACL denies".

## 8. Pydantic Schemas

### 8.1 Common primitives (`schemas/common.py`)

- `ASFUserID`: a constrained `str` (lowercase ASCII, 1..32 chars,
  matching `^[a-z][a-z0-9_-]*$`).
- `IsoTimestamp`: `datetime` with `model_config` set to serialize as
  ISO 8601 UTC.
- `RequestID`: opaque string identifier (ULID/UUID) for a CAP request.
  Globally unique across the `questions` table (enforced by the
  `UNIQUE` constraint in section 7.1) and stable for the lifetime of
  the question. Server-assigned when the question row is created;
  clients MUST NOT supply or pre-allocate a `request_id`. Returned in
  the `POST /question` response and exposed by every read endpoint so
  callers can reference the question by its opaque external id without
  having to know its numerical `question_id`.
- `QuestionID`: a positive integer issued by SQLite's `AUTOINCREMENT`
  sequence on the `questions` table. Numerical so it can be embedded
  in the pypubsub URL (section 10), and monotonic so consumers can use
  it as a stable cursor. Globally unique and assigned by the server on
  INSERT; clients MUST NOT supply or pre-allocate a `question_id`.
- `ResponseID`: opaque string (ULID/UUID) primary key of the
  `responses` table. Globally unique and assigned by the server when
  the response row is created; clients MUST NOT supply or pre-allocate
  a `response_id`.

### 8.2 Response option schemas (`schemas/responses.py`)

Different approval types accept different response shapes. To keep the
schema honest, response options are modeled as a **discriminated
union**. Each variant carries a literal `kind` field that the union
discriminates on, so that the OpenAPI document lists exactly what each
question accepts.

```python
from typing import Annotated, Literal
from pydantic import BaseModel, Field

class VoteOption(BaseModel):
    """Plus/minus vote, optionally with a comment."""
    kind: Literal["vote"] = "vote"
    allowed_values: list[Literal["+1", "+0", "-0", "-1"]] = [
        "+1", "+0", "-0", "-1",
    ]
    allow_comment: bool = True

class LazyConsensusOption(BaseModel):
    """Silence is assent; the only meaningful response is an objection."""
    kind: Literal["lazy_consensus"] = "lazy_consensus"
    allow_comment: bool = True

class FreeTextOption(BaseModel):
    """Catch-all for survey-style follow-ups."""
    kind: Literal["free_text"] = "free_text"
    max_length: int = 4000

ResponseOption = Annotated[
    VoteOption | LazyConsensusOption | FreeTextOption,
    Field(discriminator="kind"),
]
```

Submitted responses are modeled symmetrically (one variant per `kind`)
so that a future `POST /respond` endpoint can validate inbound payloads
against the same discriminator:

```python
class VoteResponse(BaseModel):
    kind: Literal["vote"] = "vote"
    value: Literal["+1", "+0", "-0", "-1"]
    comment: str | None = None

class LazyConsensusResponse(BaseModel):
    kind: Literal["lazy_consensus"] = "lazy_consensus"
    objection: bool
    comment: str | None = None

class FreeTextResponse(BaseModel):
    kind: Literal["free_text"] = "free_text"
    text: str

SubmittedResponse = Annotated[
    VoteResponse | LazyConsensusResponse | FreeTextResponse,
    Field(discriminator="kind"),
]
```

This is the meaning of "dynamic responses": the set of valid responses
is not fixed globally, it is carried by each question and validated
against the matching discriminator at submission time.

### 8.3 Question schema (`schemas/questions.py`)

A `Question` represents a single pending CAP request. It is presented
to every voter in the target audience via `/list`, and each voter's
reply is recorded as a row in the `responses` table. There is a 1:1
mapping between `request_id` and `question_id`: both are globally
unique server-assigned identifiers for the same row in the `questions`
table (the former is the opaque ULID/UUID exposed to external
consumers, the latter the numerical id used in pubsub URLs). Clients
never supply either value.

```python
class Question(BaseModel):
    question_id: QuestionID
    request_id: RequestID
    project_id: str               # ASF project id (e.g. "seapony"),
                                  # matched against session.committees

    # Human-facing
    title: str = Field(..., max_length=200)
    description: str = Field(..., max_length=10_000)

    # Provenance
    requester: ASFUserID
    target_audience: str          # e.g. "PMC: Apache SeaPony"
    created_at: IsoTimestamp
    closes_at: IsoTimestamp

    # Approval mechanics
    approval_type: Literal[
        "unanimous_approval",
        "majority_approval",
        "lazy_consensus",
    ]

    # Whether the question distinguishes binding from non-binding votes.
    # If True, only voters whose session.committees contains project_id
    # may cast a binding vote (and, for unanimous_approval questions,
    # raise a veto). Everyone else is recorded as non-binding.
    is_binding: bool

    # If True, pubsub events about this question are routed through
    # the `private/` topic prefix (see section 10). Does not affect
    # who can view or respond to the question; only the outbound
    # event stream.
    is_private: bool = False

    # What the voter is allowed to submit. Pulled from the discriminated
    # union above so the OpenAPI schema lists every concrete option.
    response_option: ResponseOption

    permalink: str | None = None  # populated once the question resolves;
                                  # of the form
                                  # f"{permalink_base}/resolution/{question_id}"

    # Lifecycle. `status` is the persisted state machine; `outcome`
    # is set whenever `status` leaves 'open' (so the two together
    # encode both the lifecycle stage and the terminal verdict).
    status: Literal["open", "resolved", "removed"] = "open"
    outcome: Literal[
        "approved",
        "vetoed",
        "insufficient_votes",
        "withdrawn",
    ] | None = None

    # Server-computed per response (NOT persisted). True if the user
    # receiving this Question would cast a binding vote on it, i.e.
    # `question.is_binding AND project_id in session.committees`.
    # Lets the UI render a "your vote will be binding" affordance
    # without re-doing the committee lookup client-side.
    viewer_is_binding: bool

    # Server-computed at response time. Seconds until `closes_at`,
    # clamped to 0 for already-closed questions. This field is *not*
    # persisted; it is filled in by the /list handler immediately
    # before serialization so clients do not have to do clock math
    # (and do not have to trust their own clock against the server's).
    time_remaining_seconds: int

class ListResponse(BaseModel):
    user: ASFUserID
    pending: list[Question]
```

`ListResponse.pending` is the "array of dictionaries" the `/list`
endpoint returns; each dictionary is the JSON encoding of a `Question`.
The `/list` handler stamps `time_remaining_seconds` on every entry
as `max(0, int((q.closes_at - now()).total_seconds()))`, computed
against the server's clock, so a value of `0` reliably means "voting
window has closed" and any positive value is a strict upper bound on
the time remaining when the response left the server. It also stamps
`viewer_is_binding` per entry, computed against the authenticated
user's `asfquart.session.committees` list.

#### 8.3.1 Approval-type semantics

The three `approval_type` values have distinct tally rules. The
`response_option` carried by a question must be compatible with its
approval type; the question creator chooses the option but the
server enforces the rules below at submission and resolution time.

- **`unanimous_approval`** — A binding voter (per `is_binding`
  resolution above) may **veto** the question by submitting a vote
  of `-1` together with a non-empty `comment` field stating their
  technical reason. The server requires the comment to be non-empty
  but does **not** judge whether the reason is technically valid:
  that determination belongs to the community. A veto without any
  comment is rejected at submission with `400 Bad Request`; a veto
  with a comment is always accepted and recorded.

  Non-binding `-1` votes are recorded but cannot veto. The question
  is approved at the deadline if and only if no veto is in force at
  that moment (see "Veto withdrawal" below).

  **Veto withdrawal.** A veto is not permanent. The voter who cast
  the veto may, at any time before resolution, submit a *new*
  response from the same ASF UID changing their vote to `+1`, `+0`,
  or `-0` (or any non-`-1` value). The latest response per
  `(question_id, voter)` is always authoritative, so submitting a
  non-veto response clears the previous veto for tally purposes; the
  old veto row remains in the `responses` table for the audit trail
  but its `is_veto=1` snapshot no longer applies because it is no
  longer the voter's latest submission. This is how the community
  records the resolution of a dispute: once the requester and the
  vetoing voter have settled their differences off-band, the
  vetoing voter resubmits and the question can proceed.

- **`majority_approval`** — All votes are counted (binding and
  non-binding, weighted per the rules of the specific request, with
  binding votes typically the deciding tally). There are no vetoes:
  a `-1` is just a counted vote against, no matter who casts it,
  and no `comment` is required.

- **`lazy_consensus`** — Silence is assent. The question is
  considered approved at the deadline provided no `-1` (or
  `LazyConsensusResponse` with `objection=True`) has been received
  during the voting window. Any objection, binding or not, blocks
  approval; a comment explaining the objection is encouraged but
  not server-enforced for non-binding objections.

Combining `is_binding=False` with `unanimous_approval` is legal but
degenerate (no voter is binding, so no veto can ever be raised); the
request creator is responsible for choosing a sensible combination.

## 9. Endpoint Specifications

### 9.1 `GET /list`

- **Auth**: required (global hook).
- **Request**: no parameters in this iteration. The user is identified
  from the session.
- **Response**: `200 OK`, body is `ListResponse` as JSON.
- **Selection rule**: every question with `status = 'open'` is a
  candidate; the result is sorted by `closes_at ASC, question_id ASC`
  so the soonest-to-close items appear first.
- **ACL filter**: the candidate set is filtered through
  `auth.can_view_question(...)` (section 7.5). Private questions
  the caller is not entitled to see are silently omitted from the
  list rather than producing a hint that they exist.
- **Per-row stamping**: for every surviving row the handler computes
  `viewer_is_binding = question.is_binding AND project_id in
  session.committees` and `time_remaining_seconds = max(0,
  int((closes_at - now_utc()).total_seconds()))`, then serializes the
  row through the `Question` Pydantic model.
- **Empty case**: `pending` is an empty array, not `null`.
- **Errors**:
  - `401 Unauthorized`: not logged in (handled by the global hook).
  - `500 Internal Server Error`: data store unavailable.

Example response:

```json
{
  "user": "alice",
  "pending": [
    {
      "question_id": 4217,
      "request_id": "req_01HZ...",
      "project_id": "seapony",
      "title": "Apache SeaPony: enable branch protection on main",
      "description": "...",
      "requester": "carol",
      "target_audience": "PMC: Apache SeaPony",
      "created_at": "2026-05-21T09:00:00Z",
      "closes_at": "2026-05-24T09:00:00Z",
      "approval_type": "majority_approval",
      "is_binding": true,
      "is_private": false,
      "response_option": {
        "kind": "vote",
        "allowed_values": ["+1", "+0", "-0", "-1"],
        "allow_comment": true
      },
      "permalink": null,
      "viewer_is_binding": true,
      "time_remaining_seconds": 259200
    }
  ]
}
```

All endpoints under `/question/` and `/resolution/` consult the
view-access ACL from section 7.5 before returning private-question
data, and apply the lifecycle/ordering rules from section 7.4 for
state changes. Question endpoints are mounted under the singular
prefix `/question/` (matching the pubsub topic layout in section
10); the `/list` endpoint and the `/api` endpoint keep their own
top-level paths.

### 9.2 `POST /question`

Create a new question. All persisted fields originate here.

- **Auth**: required.
- **Authorization**: the caller must be authorized to file a request
  on behalf of `project_id`. In this iteration that means
  `project_id` must appear in the caller's `session.committees`; a
  caller filing on behalf of a project they are not a member of
  receives `403 Forbidden`. (Admin override is via the `/admin/`
  endpoints in section 9.11, not here.)
- **Request body**: `CreateQuestionRequest` (Pydantic), carrying
  every persisted column the caller controls: `project_id`, `title`,
  `description`, `target_audience`, `approval_type`, `is_binding`,
  `is_private`, `response_option`, `closes_at`. `request_id`,
  `question_id`, `requester`, `created_at`, `updated_at`, `status`,
  `outcome`, and `permalink` are server-assigned and **must not**
  appear in the request body (the model uses `extra="forbid"`).
  `question_id` is allocated by SQLite's `AUTOINCREMENT` sequence
  when the row is inserted; `request_id` is a freshly generated
  ULID/UUID assigned in the same transaction. Neither value can be
  chosen by the client.
- **Response**: `201 Created`, body is the freshly-created
  `Question` (with the server-issued integer `question_id` and the
  computed `viewer_is_binding`/`time_remaining_seconds` fields).
  `Location: /question/{question_id}` header is set.
- **Side effects**: inserts one row into `questions`; inserts one
  `question.create` row into `audit_log` in the same transaction
  with `actor = current_user.uid`. Both writes succeed or both
  fail. After the transaction commits, an email notification is
  dispatched per section 11 (`event = "created"`, `thread_start =
  True`); a delivery failure is logged but does not roll back the
  database write.
- **Errors**: `400`/`422` (malformed body or unknown field — the
  request model uses `extra="forbid"`, so a client-supplied
  `request_id` or `question_id` is rejected here), `403` (not on the
  project's committee — root may file on behalf of any project). A
  `409` from a `request_id` collision is not expected in practice
  because the server allocates the value, but the `UNIQUE` constraint
  on `questions.request_id` still guards against bugs in the
  allocator and would surface as `409 Conflict` if it ever fired.

### 9.3 `GET /question/{question_id}`

Fetch a single question and all of its recorded responses in one
shot.

- **Auth**: required.
- **Path param**: `question_id` is an integer.
- **ACL**: subject to `auth.can_view_question(...)` (section 7.5).
  A caller without view access receives `404 Not Found`, never
  `403`, so the existence of private questions is not disclosed.
- **Response**: `200 OK`, body is a `QuestionDetail`:

  ```python
  class StoredResponse(BaseModel):
      response_id: str
      question_id: QuestionID
      voter: ASFUserID
      response_kind: Literal["vote", "lazy_consensus", "free_text"]
      response: SubmittedResponse
      comment: str | None
      is_binding: bool
      is_veto: bool
      created_at: IsoTimestamp

  class QuestionDetail(BaseModel):
      question: Question
      responses: list[StoredResponse]
  ```

  `responses` contains every row from the `responses` table for
  this question (including superseded ones), ordered by
  `created_at` ascending, so consumers can reconstruct the full
  history and observe veto withdrawals. `question.viewer_is_binding`
  and `question.time_remaining_seconds` are computed against the
  caller's session at response time, as in `/list`.
- **Errors**: `404` if no such question exists, the question's
  `status` is `removed` (visible only via `/admin/` to root users),
  or the caller's ACL check fails.

### 9.4 `PATCH /question/{question_id}`

Edit an open question's metadata.

- **Auth**: required.
- **Authorization**: only the original `requester` (or root) may
  edit. Anyone else receives `403`. Editing is forbidden once
  `status` is `resolved` or `removed` (`409 Conflict`).
- **Request body**: `EditQuestionRequest` (Pydantic), a partial
  view containing only the editable fields: `title`,
  `description`, `target_audience`, `closes_at`, `is_private`,
  `response_option`. Identity fields (`question_id`, `request_id`,
  `project_id`, `requester`, `approval_type`, `is_binding`,
  `created_at`) are not editable; attempting to set them returns
  `400`.
- **Response**: `200 OK`, body is the updated `Question`.
- **Side effects**: updates the row in `questions`, bumps
  `updated_at`, writes a `question.edit` row to `audit_log` whose
  `details_json` carries the before/after diff (only the fields
  that actually changed). Same transaction. After commit, an email
  notification is sent per section 11 (`event = "edited"`); the
  message body names the changed fields. **No-op edits** (the
  request body matches the current state) skip both the audit row
  and the email and return `200` with the unchanged `Question`.

### 9.5 `DELETE /question/{question_id}`

Withdraw an open question. This is a logical delete, not a row
deletion: the row stays in `questions` and `status` flips to
`removed`. Responses are preserved.

- **Auth**: required.
- **Authorization**: only the original `requester` (or root). Per
  section 7.4, this endpoint refuses to act on a question whose
  `status` is no longer `open`.
- **Response**: `204 No Content`.
- **Side effects**: sets `status = 'removed'` and
  `outcome = 'withdrawn'`, bumps `updated_at`, writes a
  `question.remove` row to `audit_log` with the actor's ASF UID.
  Same transaction. After commit, an email notification is sent
  per section 11 (`event = "closed"`).

### 9.6 `POST /question/{question_id}/resolve`

Finalize a question, computing the tally and issuing a permalink.

- **Auth**: required.
- **Authorization**: the original `requester`, or root. If
  `closes_at` is still in the future, only root may resolve early.
- **Request body**: empty.
- **Response**: `200 OK`, body is the resolved `Question` with
  `status = 'resolved'`, `outcome` populated (one of `approved`,
  `vetoed`, `insufficient_votes`), and `permalink` populated as
  `f"{permalink_base}/resolution/{question_id}"`.
- **Side effects**: server applies the lifecycle order from section
  7.4: it first freezes new responses (the deadline check is
  already in force if `closes_at` has passed), runs the tally per
  `approval_type` (section 8.3.1; concrete algorithm below), assigns
  `outcome`, sets `status = 'resolved'`, issues the permalink, bumps
  `updated_at`, and writes a `question.resolve` row to `audit_log`
  whose `details_json` contains the final tally (vote counts, list
  of binding voters, veto rows if any). All in one transaction.
  After commit, an email notification is sent per section 11
  (`event = "resolved"`); the message body includes the outcome and
  permalink.
- **Idempotency**: calling resolve on an already-resolved question
  returns `200` with the existing record and writes nothing to the
  audit log or the mailing list.

**Tally algorithm.** Implemented in `cap_backend/tally.py` as a
collection of pure functions over the question row and the response
rows. The resolver first reduces the response set to one row per
voter (the latest by `created_at`) before evaluating any rule, so
veto withdrawals and amended votes always count the most recent
intent.

- `unanimous_approval`: outcome is `vetoed` if any voter's *latest*
  response carries `is_veto = 1`; otherwise `approved`. Because
  `is_veto` is a snapshot taken at submission time (section 7.2),
  resubmitting a non-veto response withdraws the veto without
  touching old rows.
- `majority_approval`: tally the latest response per voter. The
  outcome is `approved` iff there is at least one binding `+1`
  and strictly more binding `+1`s than binding `-1`s; otherwise
  `insufficient_votes`. Non-binding votes are recorded in the
  audit-log tally for transparency but do not affect the outcome.
- `lazy_consensus`: outcome is `insufficient_votes` if any voter's
  latest response is either a `LazyConsensusResponse` with
  `objection=True` or a `vote` whose `value == "-1"`; otherwise
  `approved` (silence is assent).

The `details_json` payload written to `audit_log.resolve` always
includes the keys `approval_type`, `binding_voters`, `all_voters`,
and an algorithm-specific tally object (`counts` / `binding_counts`
for majority, `vetoes` for unanimous, `objections` for lazy
consensus).

**Early resolution.** Calling resolve before `closes_at` is
restricted to root (`session.isRoot`); the original requester
receives `403 deadline_in_future` until the deadline elapses.

### 9.7 `POST /question/{question_id}/responses`

Submit a new response, or amend the caller's previous response.

- **Auth**: required.
- **Authorization**: the caller's `current_user.uid` is used as
  `voter`; there is no way to vote on behalf of another user.
- **Acceptance**: governed by the ordering in section 7.4. The
  handler MUST check the deadline first (returning `409` if
  `now_utc() >= closes_at`), then the status (returning `409` if
  `status != 'open'`), then accept.
- **Request body**: a `SubmittedResponse` (the discriminated union
  from section 8.2). For `vote` responses on
  `unanimous_approval` questions, a non-empty `comment` is
  required when `value == "-1"` (the veto reason). The request body
  does **not** carry a `response_id`; the server allocates a new
  unique `response_id` (ULID/UUID) for every accepted submission,
  and clients MUST NOT attempt to supply one.
- **Server-computed fields** (not in the request body; populated
  by the handler before insert):
  - `response_id` — freshly generated ULID/UUID, unique across all
    rows in the `responses` table
  - `is_binding = question.is_binding AND
    project_id in current_user.committees`
  - `is_veto = (approval_type == 'unanimous_approval'
                AND value == '-1' AND is_binding
                AND comment != '')`
- **Response**: `201 Created`, body is the persisted
  `StoredResponse` (same shape as the entries in
  `QuestionDetail.responses`).
- **Side effects**: appends one row to `responses` (never
  overwrites previous rows from the same voter); writes a
  `question.respond` row to `audit_log` whose `response_id`
  matches the new row. Same transaction. After commit, an email
  notification is sent per section 11 (`event = "response"`).
  Submitting a non-veto response after a previous veto from the
  same voter is how a veto is withdrawn (section 8.3.1); the
  server treats it as a normal append, no special endpoint or
  flag is needed.
- **Errors**: `400` (malformed body, missing veto comment, response
  kind incompatible with the question's `response_option.kind`, vote
  `value` not present in the question's `allowed_values`, or
  free-text body exceeding `max_length`), `404` (no such question,
  or caller's ACL denies view access for a private question), `409`
  (deadline has passed, or question is not `open` per section 7.4).

**Implementation notes** (rather than rebuilding `validate_request`
around a discriminated union, the handler reads the raw JSON body and
calls `pydantic.TypeAdapter(SubmittedResponse).validate_python(...)`
itself). This keeps all per-question validation (kind compatibility,
`allowed_values` membership, `max_length` enforcement, the veto
comment requirement) in one place, immediately after the static
shape check. The `400` body distinguishes the failure mode via
`error` (`invalid_body`, `response_kind_mismatch`, `value_not_allowed`,
`text_too_long`, `missing_veto_comment`) so the UI can surface a
specific message.

### 9.8 `GET /resolution/{question_id}`

The permalink endpoint. This is the URL stored in
`question.permalink` once a question resolves, and the canonical
way for external parties to verify the outcome of a CAP question.

- **Auth**: required (the global hook applies; permalinks are not
  public).
- **Path param**: `question_id` is an integer.
- **ACL**: subject to `auth.can_view_question(...)` (section 7.5).
  ACL denial collapses into `404 Not Found`, exactly like
  `GET /question/{question_id}`.
- **Status codes**:
  - **`200 OK`** — the question resolved with
    `outcome == 'approved'`. Body is a `ResolutionRecord`:

    ```python
    class ResolutionRecord(BaseModel):
        question_id: QuestionID
        outcome: Literal["approved"]
        resolved_at: IsoTimestamp
        permalink: str
        question: Question         # the full, frozen question
        tally: dict                 # vote counts, mirror of the
                                    # question.resolve audit row
        voters: list[StoredResponse]  # final response per voter
    ```

  - **`424 Failed Dependency`** — the question reached a terminal
    state but was not approved. This covers all three rejection
    paths the user can encounter:

    | Question state                                              | `body.outcome`        |
    |-------------------------------------------------------------|-----------------------|
    | `status='resolved'`, vetoed and not withdrawn               | `"vetoed"`            |
    | `status='resolved'`, not enough votes in favor              | `"insufficient_votes"`|
    | `status='removed'` (creator withdrew before deadline)       | `"withdrawn"`         |

    Body is the same `ResolutionRecord` shape (with `outcome`
    one of the three values above). For `vetoed`, `voters`
    surfaces the veto rows so the recipient can see who vetoed
    and read their stated reason. For `withdrawn`, `tally` is
    `null`.

  - **`204 No Content`** — the question exists and the caller can
    see it, but `status == 'open'` (it has not been resolved or
    removed yet). No body.

  - **`404 Not Found`** — no question with that id exists in the
    database, **or** the caller's ACL check failed for a private
    question. Indistinguishable on the wire, deliberately.

- **Caching**: `200` and `424` responses are immutable (resolution
  outcomes never change once written) and are served with
  `Cache-Control: public, max-age=86400, immutable`. `204` and
  `404` are served with `Cache-Control: no-store`.

### 9.9 `GET /api`

- **Auth**: **public** (no login required). `/api` is the single
  exception to the global authentication hook, so external integrators
  and tooling can discover the API surface without an ASF account. The
  global `before_request` hook in `cap_backend/auth.py` allowlists this
  exact path alongside `/oauth`.
- **Request**: no parameters.
- **Response**: `200 OK`, `Content-Type: application/json`. The body is
  an OpenAPI 3.x document describing the entire HTTP API of the service,
  including request and response schemas for every other endpoint. The
  document also declares the OAuth security scheme that applies to
  every other endpoint, so `/api` is self-describing about which
  endpoints require login.
- **Generation**: the document is assembled at startup (cached) from the
  Pydantic models registered with `quart-schema`. The endpoint itself
  simply returns the cached document. There is no hand-maintained
  OpenAPI YAML.
- **Stability**: the OpenAPI document includes the service version
  (from `pyproject.toml`) in `info.version`, so consumers can detect
  breaking changes.
- **Caching**: the response carries `Cache-Control: public, max-age=300`
  since the document only changes when the service is redeployed.

`/api` itself is included in the document it returns.

### 9.10 `GET /docs`

- **Auth**: **public** (no login required). `/docs` is exempt from the
  global authentication hook for the same reason `/api` is: external
  integrators must be able to browse the API surface without an ASF
  account. The path is added to the allowlist in
  `cap_backend/auth.PUBLIC_PATHS` alongside `/api`.
- **Request**: no parameters.
- **Response**: `200 OK`, `Content-Type: text/html; charset=utf-8`.
  The body is a small, self-contained HTML document that loads
  [Swagger UI](https://swagger.io/tools/swagger-ui/) from a public CDN
  (`cdn.jsdelivr.net/npm/swagger-ui-dist`, pinned to a specific
  major.minor.patch in `cap_backend/openapi.py`) and points it at
  `/api` for the OpenAPI document. There are no server-side schemas
  embedded in the page; rebuilds of the OpenAPI document at `/api`
  are reflected automatically the next time the page is loaded (or
  the next time `/api` is re-fetched from cache, whichever comes
  first).
- **Generation**: the HTML body is a constant string assembled at
  import time. There is no per-request rendering and no template
  engine; the only dynamic input is the pinned swagger-ui version,
  which is a module-level constant.
- **Caching**: the response carries `Cache-Control: public, max-age=300`
  for parity with `/api`. Because the body never changes between
  service restarts (it is a static HTML literal), this is purely a
  network-traffic optimization.
- **Security note**: the page is served at a *public* URL but the
  underlying API is not — every endpoint listed in the rendered
  spec still requires the OAuth login declared in the document's
  `security` block. "Try it out" calls from inside Swagger UI will
  receive a `401` JSON response (or a redirect to `/auth` for
  text/html callers) until the caller has logged in through the
  same browser session.

### 9.11 Administrative endpoints

Administrative endpoints are reserved for SRE-level recovery actions
(initially, reissuing a permalink after a corrupted resolve, and
force-removing a question stuck in an inconsistent state). They live
under a dedicated path prefix, `/admin/...`, and are protected by an
additional decorator on top of the global authentication hook:

```python
import asfquart
from asfquart.auth import Requirements as R

@app.route("/admin/reissue-permalink", methods=["POST"])
@asfquart.auth.require(R.root)
async def reissue_permalink():
    ...
```

`asfquart.auth.require(R.root)` enforces `session.isRoot == True` on
the request session; non-root authenticated users receive a `403
Forbidden` from the decorator (the global hook will have already
rejected unauthenticated requests with `401`).

The set of concrete admin endpoints is intentionally not enumerated
in this iteration. The convention this section establishes is:

1. All admin endpoints are mounted under `/admin/`.
2. Every admin handler carries `@asfquart.auth.require(R.root)`.
3. Every admin action writes to `audit_log` like any other state
   change, with `actor` set to the root user's ASF UID (never
   `system`, so root-initiated actions are distinguishable in the log).
4. Admin endpoints appear in the OpenAPI document like any other
   endpoint, with their root-requirement reflected in the
   `security` block so external tooling can see they are restricted.

## 10. Pubsub Publishing

State-changing actions are republished to a [pypubsub] instance so
that downstream subscribers (auditors, dashboards, project tooling)
can react in near-real-time without polling the API.

[pypubsub]: https://github.com/humbedooh/pypubsub

### 10.1 Transport

pypubsub accepts events as JSON dictionaries POSTed (or PUT) to a URL
whose **path is the topic**. The publisher in this service uses
`POST` (PUT is also accepted by pypubsub; either works). The base URL
and credentials are configured in `config.yaml` under `pubsub:`
(section 5.1).

The full pseudo-URL for an event is:

```
{base_url}[/private]/question/{type}/{project}/{id}
```

- `base_url` — from `config.yaml`.
- `/private` — inserted as the *first* topic segment after `base_url`
  when, and only when, the originating question has `is_private = 1`.
  This matches pypubsub's private-topic convention; subscribers without
  the right basic-auth credentials will not see private events.
- `question` — fixed literal.
- `{type}` — one of: `created`, `response`, `resolved`, `edited`,
  `closed`. Mapping from audit-log actions:

  | `audit_log.action`   | `{type}` segment |
  |----------------------|------------------|
  | `question.create`    | `created`        |
  | `question.respond`   | `response`       |
  | `question.resolve`   | `resolved`       |
  | `question.edit`      | `edited`         |
  | `question.remove`    | `closed`         |

- `{project}` — the question's `project_id` (e.g. `seapony`).
- `{id}` — the question's numerical `question_id` (e.g. `4217`).

Example URLs:

```
https://pubsub.apache.org:2069/question/created/seapony/4217
https://pubsub.apache.org:2069/private/question/response/infra/9001
```

### 10.2 Payload

Each event body is a JSON dictionary (pypubsub rejects non-dict
bodies). The body always contains:

- `action` — the action type, e.g. `"created"` (mirrors the
  type segment so subscribers don't have to parse the URL).
- `question` — a serialized `Question` model (the same shape
  `/list` returns) for the question the event is about.
- `actor` — the ASF UID of the user who performed the action.
- `occurred_at` — ISO-8601 UTC timestamp of the audit row.
- `audit_id` — the `audit_log.audit_id` of the row that produced
  this event. Subscribers can use this as a stable, monotonic
  cursor across all event types.

For `response`-type events the body additionally contains:

- `response` — the persisted response including its snapshot
  fields (`voter`, `is_binding`, `is_veto`, `comment`,
  `response_kind`, `response_json`).

For `resolved`-type events the body additionally contains:

- `tally` — the same structure that was written into
  `audit_log.details_json` at resolve time (vote counts, binding
  voter list, veto rows if any), and the final `permalink`.

For `edited`-type events the body additionally contains:

- `diff` — an object with one key per field that actually changed,
  whose value is `{"before": ..., "after": ...}`.

### 10.3 PII exclusion

Pubsub events are intended for broad consumption (and, for public
topics, may be replayed indefinitely). They MUST exclude personally
identifiable information that does not need to leave the service:

- **Excluded**: client IP addresses, request headers, OAuth tokens
  or session cookies, email addresses, real names, anything sourced
  from the OAuth identity beyond the ASF UID and committee
  membership.
- **Included**: ASF UIDs (treated as public identifiers within ASF
  context), committee/project ids, question metadata, response
  payloads (comments included; voters opt into having their
  comments public when they submit).

The serializer for pubsub bodies lives in `cap_backend/pubsub.py` and
is the **only** sanctioned place that converts internal records to
outbound JSON. It must not have access to a raw HTTP request object;
it works exclusively from rows already persisted in SQLite, which by
construction do not contain IP addresses or other request-time PII.

### 10.4 Delivery and reliability

- The publisher is a background coroutine started by
  `cap_backend/app.py` on `app.startup`. It tails `audit_log`
  ordered by `audit_id` and POSTs one event per row.
- The last successfully published `audit_id` is stored in a tiny
  `pubsub_cursor` table (one row, one column) inside the same
  SQLite database, so restarts resume where the previous run left
  off without re-emitting events.
- A non-2xx response from pypubsub causes the publisher to retry
  with exponential backoff. It does **not** advance the cursor
  past a failing row, so events are delivered at-least-once and
  in `audit_id` order.
- If `pubsub.enabled = false` in `config.yaml`, the publisher
  coroutine never starts and `audit_log` simply accumulates;
  re-enabling the publisher later will drain the backlog from
  the stored cursor.
- Private events for which no `basic_auth` credentials are
  configured are skipped (logged at `WARNING`); the cursor still
  advances, so the audit log remains the source of truth, but the
  pubsub stream may be incomplete from that operator's vantage
  point.

## 11. Email Notifications

Every state-changing action on a question is also broadcast to the
project's mailing list via `asfpy.messaging.mail` so that humans on
the relevant PMC see the activity without having to subscribe to the
pypubsub stream. Pubsub (section 10) is the machine-readable channel;
email is the human-readable one.

### 11.1 Recipient selection

The recipient list is determined entirely by the question's
`project_id` and `is_private` flag:

| `is_private` | Recipient                              |
|--------------|----------------------------------------|
| `False`      | `dev@{project_id}.apache.org`          |
| `True`       | `private@{project_id}.apache.org`      |

The selection lives in `cap_backend/notify.recipient_for(question)`
so handlers never have to know mailing-list naming conventions.
There is exactly one mailing-list recipient per event; no Cc / Bcc.

### 11.2 Sender

The `From:` header is constant across every event so subscribers
can filter on it:

```
From: ASF Contingent Approval Platform <root-asfcap@apache.org>
```

Replies are not expected (the address is a posting source, not a
mailbox); subscribers wishing to discuss should reply on the list
itself.

### 11.3 Subject and threading

Subject lines follow `[CAP] <verb> #<question_id>: <title>`, with
`<verb>` selected from:

| `event`     | Subject prefix             | Audit-log action     |
|-------------|----------------------------|----------------------|
| `created`   | `[CAP] New question`       | `question.create`    |
| `edited`    | `[CAP] Question updated`   | `question.edit`      |
| `resolved`  | `[CAP] Question resolved`  | `question.resolve`   |
| `closed`    | `[CAP] Question withdrawn` | `question.remove`    |
| `response`  | `[CAP] New response`       | `question.respond`   |

All events for the same question share a deterministic threading
key (`cap-question-<question_id>`). `event = "created"` sets
`thread_start = True`; every subsequent event uses the same key as
`thread_key`, which makes `asfpy.messaging.mail` set an
`In-Reply-To` header pointing at the original `Message-ID`. The
list archive therefore renders every event under one thread.

### 11.4 Body

The body is plaintext; the first three lines are always:

```
Actor: <asf-uid>
Question id: <numeric>
Project: <project_id>
Event: <event>
```

Followed by a blank line and an event-specific summary (the
question title and approval type for `created`, the changed
fields for `edited`, the outcome and permalink for `resolved`,
etc.). Bodies are intentionally terse: the audit log and the
permalink endpoint are the canonical sources for full state.

### 11.5 PII

The email recipient set is identical to the existing project
mailing lists, so the standard ASF mail-handling guarantees
apply (private posts are list-restricted; public posts may be
archived publicly). The notifier itself, like the pubsub
publisher (section 10.3), works exclusively from rows already
persisted in SQLite and therefore cannot disclose request-time
PII such as client IP addresses or session cookies.

### 11.6 Reliability

`notify.send(...)` never raises. Any failure inside
`asfpy.messaging.mail` (misconfigured MSA in dev, transient SMTP
failure in prod) is caught and logged at `WARNING`; the function
returns `False`. This is deliberate: the audit log is the durable
record of the action, and an email failure must not roll back a
state change that has already committed to the database. Operators
who need stronger delivery guarantees should consume the pubsub
stream instead.

Email dispatch happens **after** the SQLite transaction commits,
not inside it. Conversely, the audit-log insert always happens
**inside** the transaction, so the invariant "audit row exists ⇒
state change took effect" is preserved even when the MSA is
down.

## 12. Logging and Observability

- All requests are logged at INFO with method, path, status, latency,
  and the ASF UID (or `-` for unauthenticated `/auth` traffic).
- Authentication failures (the global hook returning 401) are logged
  at WARNING with the requested path.
- The pubsub publisher (section 10) logs each POST at DEBUG with the
  target URL (private events log only the topic suffix, never the
  basic-auth header); failures log at WARNING.
- The email notifier (section 11) logs each successful dispatch at
  INFO via the asfpy stack; failures inside `notify.send` log at
  WARNING with the question id and event type, and are swallowed.

## 13. Testing Notes

The test suite lives under `backend/tests/` and runs through
`uv run pytest`. The GitHub workflow at
`.github/workflows/backend-ci.yml` runs `ruff check`,
`ruff format --check` and `pytest` on every push and pull request
that touches the backend.

Standing fixtures (in `tests/conftest.py`):

- `app`: a fully-built `QuartApp` against a fresh temporary SQLite
  database. Lifecycle is managed by `application.test_app()` so the
  DB connection is closed cleanly between tests.
- `stub_session`: monkeypatches `cap_backend.auth._read_session` to
  return a session for the default fixture user (`alice` on
  `seapony`). Tests that need a different user use `as_user(...)`
  instead.
- `as_user`: yields a setter that swaps in a specific
  `AuthenticatedUser` (e.g. a root user, or an outsider) so a single
  test can exercise authorization branches without rebuilding the
  app.
- `captured_emails`: monkeypatches `cap_backend.notify._send_mail` to
  append every dispatched message to a list. Tests assert on
  `recipient`, `sender`, `subject`, `message`, `thread_start`, and
  `thread_key`. No SMTP traffic ever leaves the test process.
- `seed_questions` / `seed_response`: low-level inserts that bypass
  the HTTP layer, used to set up state for read-side and resolver
  tests.

Coverage by area:

- **Schema round-tripping** (`test_schemas.py`): every Pydantic
  model is exercised with a small set of fixture JSON payloads;
  the response discriminator is checked for each `kind`; the
  `ASFUserID` regex is verified.
- **`/api`** (`test_api_endpoints.py`): asserts the response is
  reachable without authentication, has `openapi: "3.x.y"`, lists
  `/list`, `/api`, and the management endpoints in `paths`,
  populates `components.schemas` with `Question`, `VoteOption`,
  `LazyConsensusOption`, `FreeTextOption`, and references
  `ListResponse` / `AuthenticationRequired` from `/list`'s
  responses.
- **`/list`** (`test_api_endpoints.py`): tested unauthenticated
  with `Accept: application/json` (expect 401 JSON) and with
  `Accept: text/html` (expect 30x redirect to `/auth`), then
  authenticated against seeded fixtures (expect `ListResponse`
  with a positive `time_remaining_seconds`, viewer-binding flag
  set when the user is on the project's committee, private
  questions filtered, resolved/removed questions omitted).
- **Question management** (`test_question_management.py`):
  end-to-end tests for `POST /question`,
  `GET /question/{id}`, `PATCH /question/{id}`,
  `DELETE /question/{id}`, and `POST /question/{id}/resolve`.
  Each test asserts the HTTP response, the audit-log row written,
  and the email captured by `captured_emails` (recipient, sender,
  subject prefix, threading). Authorization branches covered:
  non-committee 403, non-requester 403, root override, early-
  resolve restriction.
- **Response submission** (`test_responses.py`): end-to-end tests
  for `POST /question/{id}/responses` covering the happy path for
  each `kind` (vote, lazy_consensus, free_text), the veto rules
  (binding -1 without comment rejected as `400`, with comment
  recorded as `is_veto=1`, non-binding -1 recorded but never veto),
  veto withdrawal as an appended row, `response_option`
  compatibility (kind mismatch, value outside `allowed_values`,
  free-text overflow), `§7.4` acceptance ordering (deadline-passed
  and not-open both `409`), the `404` ACL collapse for private
  questions, malformed bodies, and the resulting audit row /
  email side effects.
- **Resolver** (`test_question_management.py`): unanimous with
  active veto returns `vetoed`; unanimous with a *withdrawn* veto
  (same voter resubmits non-`-1`) returns `approved` (latest
  response per voter wins); lazy consensus with any objection
  returns `insufficient_votes`; majority with no binding votes
  returns `insufficient_votes`. Idempotency: resolving an
  already-resolved question returns 200 with the existing record
  and writes neither an audit row nor an email.
- **Auth helpers** (`test_auth.py`): `is_public_path`, the
  JSON-vs-HTML branch in the 401 hook, and every branch of
  `can_view_question` (public, private + committee, private +
  root, private + `tooling` committee, private + outsider).
- **Config** (`test_config.py`): rejects unknown keys, honors the
  CLI/`CAP_CONFIG`/cwd/`/etc/cap/` resolution order, and folds
  `CAP_PUBSUB_PASSWORD` into the loaded settings.
- **Database** (`test_db.py`): bootstrap is idempotent; the
  audit-log `CHECK (action IN ...)` constraint rejects unknown
  action names.
- **Response normalizer** (`test_response_normalizer.py`):
  regression test pinning the `ClientSession`-to-`dict` fix from
  section 3.1.
- **Pubsub** (`test_pubsub.py`): unit tests for the URL builder
  (the `/private/` prefix appears exactly when `is_private=1`,
  the trailing-slash on `base_url` is normalized) and the
  cursor read/write helpers; payload-assembly tests for every
  `{type}` (`created`, `edited`, `response`, `resolved`,
  `closed`) confirming the per-type extra fields
  (`response` / `tally` + `permalink` / `diff`); a PII test
  that fails if anything resembling an IP, cookie, session
  token or email address appears in the serialized payload;
  and end-to-end tests with a fake send callable confirming
  the cursor advances exactly on success, stays put on
  non-2xx responses and on raised exceptions, that ordering
  by `audit_id` is preserved, that private events without
  credentials are skipped with a `WARNING` while the cursor
  still advances, and that the publisher consumes audit rows
  produced by `POST /question` through the real HTTP route.

## 14. Open Questions

All previously-open items have been folded into the body of this
document. There are no unresolved design questions blocking the
current implementation iteration; the list below is preserved as a
ledger of where each decision lives so reviewers can audit the
trail without re-reading the whole document.

1. **Binding eligibility** is `questions.is_binding` plus a
   committee-membership check (sections 7.2 and 8.3.1).
2. **Audit log retention** is indefinite (section 7.3).
3. **Admin endpoints** require `session.isRoot` via
   `@asfquart.auth.require(R.root)` (section 9.11).
4. **Veto validity** is a community matter, not a server matter:
   the server requires only a non-empty comment, and vetoes can be
   withdrawn by the original voter submitting a non-`-1` response
   (section 8.3.1).
5. **Question management endpoints** (create / fetch / edit /
   remove / resolve) are implemented in sections 9.2 through 9.6.
   Each handler writes its audit row inside the SQLite transaction
   that performs the state change, and dispatches an email
   notification per section 11 after the transaction commits.
6. **Response submission** (`POST /question/{id}/responses`,
   section 9.7) is implemented. The handler enforces the §7.4
   acceptance order (deadline check first, then status), computes
   `is_binding` and `is_veto` as snapshots at submission time
   (§7.2), and writes one row to `responses` plus a
   `question.respond` row to `audit_log` in the same transaction.
   After commit, an email is dispatched per section 11 with
   `event = "response"`. The handler additionally rejects
   submissions whose `kind` does not match the question's
   `response_option.kind`, whose `value` is not in
   `response_option.allowed_values` for `vote`-typed questions,
   or whose `text` exceeds `response_option.max_length` for
   free-text questions.
7. **Pubsub publisher** is implemented in `cap_backend/pubsub.py`
   (section 10). A single background coroutine, started by
   `cap_backend/app.py` on `app.startup` when
   `settings.pubsub.enabled` is true, tails `audit_log` ordered
   by `audit_id` and POSTs one JSON event per row to
   `{base_url}[/private]/question/{type}/{project}/{id}`. The
   last successfully delivered `audit_id` is persisted in the
   `pubsub_cursor` table, so restarts resume without re-emitting
   events. Failures pause the loop with exponential backoff up
   to 60 s and never advance the cursor, giving at-least-once
   delivery in `audit_id` order. Private events for which no
   `basic_auth` credentials are configured are skipped (logged
   at `WARNING`) while the cursor still advances, exactly as
   described in §10.4.
8. **Email notifications** route to
   `dev@{project}.apache.org` for public questions and
   `private@{project}.apache.org` for private questions, always
   from `ASF Contingent Approval Platform
   <root-asfcap@apache.org>` (section 11). Dispatch failures are
   logged and swallowed so a misconfigured MSA cannot roll back a
   committed state change.
9. **Permalink format** is
   `f"{permalink_base}/resolution/{question_id}"` (section 9.6),
   served by `GET /resolution/{question_id}` (section 9.8). The
   permalink uses the question's numerical id directly and
   distinguishes approved (`200`), terminal-but-not-approved
   (`424`), pending (`204`), and absent-or-unauthorized (`404`)
   states.
10. **Private-question ACL** is `auth.can_view_question(...)` in
    section 7.5: viewer must be root, on the question's project
    committee, or on the `tooling` committee. ACL denial collapses
    into `404` on every read endpoint to avoid disclosing existence.
11. **Concurrency on resolve** follows the canonical ordering in
    section 7.4: deadline first (absolute), then status. A response
    arriving after `closes_at` is rejected with `409` even if it
    was queued before the deadline elapsed.
12. **Resolver tally algorithm** is implemented in
    `cap_backend/tally.py` and specified in section 9.6 (latest
    response per voter; per-`approval_type` rules; tally summary
    persisted to `audit_log.resolve.details_json`).

Items deferred to a future iteration (not blocking this cut):

- **`GET /resolution/{question_id}`** (section 9.8) — the permalink
  endpoint is specified but not yet implemented; the permalink
  string is already written into the `questions.permalink` column
  at resolve time.
- **Pagination on `GET /question/{question_id}`** is unbounded in
  this spec (all responses returned). If a single question
  accumulates thousands of responses, paginating the `responses`
  array will be needed; the shape (cursor vs. offset, default
  page size) is left to a follow-up.
