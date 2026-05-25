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

| Method   | Path                       | Auth | Purpose                                            |
|----------|----------------------------|------|----------------------------------------------------|
| `GET`    | `/api`                     | none | OpenAPI 3.x document for the whole service         |
| `GET`    | `/auth`                    | none | asfquart OAuth gateway (login / logout handshake)  |
| `GET`    | `/list`                    | yes  | Open questions visible to the caller (SPEC §9.1)   |
| `POST`   | `/question`                | yes  | Create a new question (SPEC §9.2)                  |
| `GET`    | `/question/{id}`           | yes  | Fetch one question plus all responses (SPEC §9.3)  |
| `PATCH`  | `/question/{id}`           | yes  | Edit an open question's metadata (SPEC §9.4)       |
| `DELETE` | `/question/{id}`           | yes  | Withdraw an open question (SPEC §9.5)              |
| `POST`   | `/question/{id}/resolve`   | yes  | Finalize the tally and issue the permalink (§9.6)  |
| `POST`   | `/question/{id}/responses` | yes  | Submit / amend a response (SPEC §9.7)              |

`/api` is the only public route; every other path is gated by the
global authentication hook, which redirects browser clients to
`/auth?login=<return-path>` and returns `401` JSON to API clients.

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

- `GET /resolution/{id}` (SPEC §9.8). The permalink string is
  already written into `questions.permalink` at resolve time, but
  the read endpoint that serves it is deferred to the next
  iteration.

## Persistence

SQLite 3 in WAL mode at the path given by `database.path` in
`config.yaml`. The schema is materialized on first launch via
`CREATE TABLE IF NOT EXISTS` (see `cap_backend/sql/schema.sql`).
Tables: `questions`, `responses`, `audit_log`, `pubsub_cursor`.

## Configuration

`config.yaml` is documented in SPEC §5.1. The fields that matter
operationally:

- `server.permalink_base` — production should set this to the
  public host so `permalink` values render as
  `https://cap.apache.org/resolution/{id}`. Defaults to empty,
  yielding bare paths (handy in dev).
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
│   └── questions.py   # /list, /question/*, /question/<id>/resolve,
│                      # /question/<id>/responses
├── tally.py      # pure resolve-time tally rules (§9.6)
├── audit.py      # audit-log writer (caller owns the txn)
├── notify.py     # asfpy.messaging.mail dispatch (§11)
├── pubsub.py     # background publisher tailing audit_log (§10)
├── openapi.py    # /api endpoint
└── schemas/      # Pydantic models (questions, responses, errors)
```

## AI-assisted development

This application was developed using AI-assisted technology. The
inputs provided to the AI consist of copyleft and/or fair-use of
publicly available material, together with direct human input and
guidance. The resulting output (the source code in this repository)
is licensed under the Apache License, Version 2.0. See the
[`LICENSE`](../LICENSE) file at the repository root for the full text.
