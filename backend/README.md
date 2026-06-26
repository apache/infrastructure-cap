# CAP Backend

Python backend for the ASF Infra Contingent Approval Provider (CAP).
See [`SPEC.md`](./SPEC.md) for the full design. This README is the
operator-facing summary: how to run it, what it currently exposes,
and where to look when something is off.

## Quick start

```bash
# install / sync dependencies into .venv
uv sync --extra dev

# run the server (defaults to http://0.0.0.0:8085)
uv run cap-backend

# run with a specific config file
uv run cap-backend --config ./config.yaml
```

The config file path is resolved in this order:

1. `--config <path>` CLI argument
2. `CAP_CONFIG` environment variable
3. `./config.yaml` in the working directory
4. `/etc/cap/config.yaml`

A starter `config.yaml` lives in this directory; copy it before
editing for a real deployment.

## What is implemented

The current iteration ships the full CAP workflow except the
public-permalink read endpoint. Everything below is wired end to end:
HTTP route, Pydantic-validated request/response, audit-log row in
the same SQLite transaction, mailing-list email after commit, and
pubsub event tailed from the audit log.

### HTTP endpoints

All backend routes are namespaced under the `/api/` prefix. The
asfquart-owned OAuth gateway at `/auth` is the one exception (it has
to be reachable without a session in order to perform the login
handshake).

| Method   | Path                           | Auth  | Scope    | Purpose                                            |
|----------|--------------------------------|-------|----------|----------------------------------------------------|
| `GET`    | `/api/api`                     | none  | n/a      | OpenAPI 3.x document for the whole service         |
| `GET`    | `/api/docs`                    | none  | n/a      | Swagger UI rendering of `/api/api` (SPEC §9.10)    |
| `GET`    | `/api/publist`                 | none  | n/a      | Public feed of non-private questions (SPEC §9.13)  |
| `GET`    | `/auth`                        | none  | n/a      | asfquart OAuth gateway (login / logout handshake)  |
| `GET`    | `/api/list`                    | yes   | `public` | Open questions visible to the caller (SPEC §9.1)   |
| `POST`   | `/api/question`                | yes   | `ask`    | Create a new question (SPEC §9.2)                  |
| `GET`    | `/api/question/{id}`           | yes   | `public` | Fetch one question plus all responses (SPEC §9.3)  |
| `PATCH`  | `/api/question/{id}`           | yes   | `ask`    | Edit an open question's metadata (SPEC §9.4)       |
| `DELETE` | `/api/question/{id}`           | yes   | `ask`    | Withdraw an open question (SPEC §9.5)              |
| `POST`   | `/api/question/{id}/resolve`   | yes   | `ask`    | Finalize the tally and issue the permalink (§9.6)  |
| `POST`   | `/api/question/{id}/responses` | yes   | `answer` | Submit / amend a response (SPEC §9.7)              |
| `GET`    | `/api/token`                   | OAuth | n/a      | Issue a personal-access bearer token (SPEC §9.12)  |

`/api/api`, `/api/docs`, and `/api/publist` are the only public
routes; every other path is gated by the global authentication hook,
which redirects browser clients to `/api/auth?login=<return-path>`
and returns `401` JSON to API clients. Endpoints listed by Swagger UI
at `/api/docs` are still auth-gated when invoked via "Try it out".

### Authentication and scopes

Authenticated callers come in two flavors:

- **OAuth sessions**, established via the `/auth` gateway. These hold
  every scope implicitly, and are the only sessions allowed to issue
  new personal-access tokens.
- **Bearer-token sessions**, established by sending
  `Authorization: bearer <token>` against any route. asfquart resolves
  the token through `APP.token_handler`, which `cap_backend/app.py`
  wires to an in-memory `TokenStore`. Token sessions are restricted to
  the scopes recorded at issuance time (currently always `["ask"]`).

The scope check happens inline in each handler: a token whose scope
list does not include the route's required scope receives `403` with
body `{"error": "insufficient_scope", "required_scope": "<scope>"}`.
The `public` scope is granted to every authenticated caller and is
the catch-all for read-only endpoints.

### Personal access tokens (`GET /api/token`)

A logged-in user calls `GET /api/token` to mint a fresh bearer token.
The response includes the token string (shown exactly once), the
issued scope list (always `["ask"]`), the creation timestamp, and an
absolute expiry 24 hours later. Constraints:

- Tokens live only in process memory. Restarts and process recycles
  invalidate every outstanding token.
- A single ASF UID may hold at most five live tokens at any moment.
  Issuing a sixth evicts the oldest in FIFO order.
- Token sessions cannot themselves issue further tokens: an attempt
  receives `403 token_session_cannot_issue`.
- Token holders can create, edit, withdraw, and resolve questions
  (scope `ask`) plus read public-scope endpoints, but they cannot
  submit responses (which require the `answer` scope).

### Side effects, automatic on every state change

- **Audit log.** Every `POST` / `PATCH` / `DELETE` writes one row
  to `audit_log` in the same SQLite transaction as the table-level
  change. The log is append-only and is the source of truth for
  the pubsub publisher.
- **Email.** After the transaction commits, the route dispatches a
  notification through `asfpy.messaging.mail`. Public questions
  route to `dev@{project}.apache.org`; private questions route to
  `private@{project}.apache.org`. Delivery failures are logged but
  never roll back a committed state change.
- **Pubsub.** A background coroutine (`cap_backend/pubsub.py`)
  tails `audit_log` by `audit_id` and POSTs one JSON event per
  row to `{pubsub.base_url}[/private]/question/{type}/{project}/{id}`.
  Cursor state lives in the `pubsub_cursor` table, so restarts
  resume cleanly. Failures pause with exponential backoff up to
  60 s and never advance the cursor, giving at-least-once
  delivery in `audit_id` order. The publisher is gated on
  `pubsub.enabled` in `config.yaml`.

## What is not implemented yet

- `GET /api/resolution/{id}` (SPEC §9.8). The permalink string is
  already written into `questions.permalink` at resolve time, but
  the read endpoint that serves it is deferred to the next
  iteration.

## Persistence

SQLite 3 in WAL mode at the path given by `database.path` in
`config.yaml`. On startup the **migration runner**
(`cap_backend/migrations.py`) brings the database up to the current
schema: a fresh database is built from `cap_backend/sql/migrations/0001`
forward, a database created by an older release is upgraded in place
(its applied versions are tracked in `schema_migrations`), and an
up-to-date database is left untouched. To change the schema, add a new
numbered migration under `cap_backend/sql/migrations/` and regenerate the
`cap_backend/sql/schema.sql` snapshot to match (SPEC §7.6). Tables:
`questions`, `responses`, `audit_log`, `pubsub_cursor`,
`schema_migrations`.

## Configuration

`config.yaml` is documented in SPEC §5.1. The fields that matter
operationally:

- `server.permalink_base` — production should set this to the
  public host so `permalink` values render as
  `https://cap.apache.org/api/resolution/{id}`. Defaults to empty,
  yielding bare paths (handy in dev).
- `server.publist_cache_seconds` — max age, in seconds, of the
  in-process cache that backs `/api/publist` (SPEC §9.13). Default
  `30`; `0` disables caching so every request recomputes. The
  endpoint's `Cache-Control` header mirrors this value.
- `database.path` — absolute or relative path to the SQLite file.
  The parent directory must exist and be writable.
- `pubsub.enabled` — set to `false` to disable the background
  publisher entirely (events still accumulate in `audit_log` and
  drain when the publisher is re-enabled).
- `pubsub.basic_auth` — username/password for posting to private
  topics. Without credentials, private events are skipped (with a
  `WARNING` log line) while public events continue to be
  delivered.
- `CAP_PUBSUB_PASSWORD` — environment override for
  `pubsub.basic_auth.password`, so the password never has to live
  in the YAML file.

## Development

```bash
# lint
uv run ruff check .

# tests
uv run pytest
```

CI runs the same `ruff check` and `pytest` on every push and PR
(see `.github/workflows/backend-ci.yml`).

## Layout cheat sheet

```
cap_backend/
├── app.py        # build_app() + while_serving lifecycle hooks
├── auth.py       # global auth hook, AuthenticatedUser, ACL helper
├── config.py     # Pydantic Settings + config.yaml resolution
├── db.py         # SQLite connection, schema bootstrap, write lock
├── dao.py        # row <-> Pydantic projections + insert/update helpers
├── routes/
│   ├── questions.py   # /api/list, /api/question/*, /api/question/<id>/resolve,
│   │                  # /api/question/<id>/responses
│   └── tokens.py      # /api/token (issue personal-access token)
├── tokens.py     # in-memory bearer-token store + token_handler factory
├── tally.py      # pure resolve-time tally rules (§9.6)
├── audit.py      # audit-log writer (caller owns the txn)
├── notify.py     # asfpy.messaging.mail dispatch (§11)
├── pubsub.py     # background publisher tailing audit_log (§10)
├── openapi.py    # /api/api (OpenAPI doc) and /api/docs (Swagger UI)
└── schemas/      # Pydantic models (questions, responses, errors)
```

## AI-assisted development

This application was developed using AI-assisted technology. The
inputs provided to the AI consist of copyleft and/or fair-use of
publicly available material, together with direct human input and
guidance. The resulting output (the source code in this repository)
is licensed under the Apache License, Version 2.0. See the
[`LICENSE`](../LICENSE) file at the repository root for the full text.
