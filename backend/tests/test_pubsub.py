"""Tests for the pubsub publisher (SPEC §10).

The publisher tails ``audit_log`` and POSTs JSON events to a pypubsub
instance. These tests stub the HTTP send callable so we never touch the
network, then drive the publisher synchronously by invoking
``_process_batch`` (the unit of work the background loop calls in a
loop) and asserting on the captured POSTs and the cursor row.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from cap_backend import audit
from cap_backend.config import DatabaseSettings, PubsubBasicAuth, PubsubSettings, Settings
from cap_backend.pubsub import (
    PubsubPublisher,
    build_event_payload,
    build_url,
    read_cursor,
    write_cursor,
)

# ---------------------------------------------------------------------------
# Fake send callable
# ---------------------------------------------------------------------------


class FakeSender:
    """Collect POSTs without touching the network.

    Each call records ``url``, ``payload``, ``headers`` and ``timeout``.
    ``return_status`` is the HTTP code returned to the publisher; set it
    to a non-2xx value to simulate pypubsub failures.
    """

    def __init__(self, return_status: int = 200, *, raise_exc: Exception | None = None):
        self.calls: list[dict[str, Any]] = []
        self.return_status = return_status
        self.raise_exc = raise_exc

    async def __call__(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> int:
        self.calls.append(
            {
                "url": url,
                "payload": payload,
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.return_status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_with(tmp_db_path: str, **pubsub_overrides: Any) -> Settings:
    pubsub_kwargs: dict[str, Any] = {
        "enabled": True,
        "base_url": "https://pubsub.example/cap",
        "basic_auth": PubsubBasicAuth(username=None, password=None),
        "timeout_seconds": 5,
    }
    pubsub_kwargs.update(pubsub_overrides)
    return Settings(
        database=DatabaseSettings(path=tmp_db_path),
        pubsub=PubsubSettings(**pubsub_kwargs),
    )


async def _process_until_done(publisher: PubsubPublisher, max_iters: int = 10) -> None:
    """Run _process_batch until it stops making progress."""
    for _ in range(max_iters):
        progressed = await publisher._process_batch()
        if not progressed:
            return
    raise AssertionError("publisher did not drain its backlog within max_iters")


# ---------------------------------------------------------------------------
# URL builder unit tests
# ---------------------------------------------------------------------------


def test_build_url_public():
    assert (
        build_url(
            "https://pubsub.example/cap",
            is_private=False,
            event_type="created",
            project="seapony",
            question_id=4217,
        )
        == "https://pubsub.example/cap/question/created/seapony/4217"
    )


def test_build_url_private_inserts_prefix():
    assert (
        build_url(
            "https://pubsub.example/cap",
            is_private=True,
            event_type="response",
            project="infra",
            question_id=9001,
        )
        == "https://pubsub.example/cap/private/question/response/infra/9001"
    )


def test_build_url_strips_trailing_slash():
    assert (
        build_url(
            "https://pubsub.example/cap/",
            is_private=False,
            event_type="resolved",
            project="x",
            question_id=1,
        )
        == "https://pubsub.example/cap/question/resolved/x/1"
    )


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------


async def test_cursor_starts_at_zero(app):
    db = app.extensions["cap_db"]
    assert read_cursor(db.conn) == 0


async def test_cursor_round_trip(app):
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    write_cursor(db.conn, 42)
    db.conn.execute("COMMIT")
    assert read_cursor(db.conn) == 42


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------


async def test_build_event_payload_includes_required_fields(app, stub_session, seed_questions):
    [qid] = seed_questions(app, count=1)
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    audit_id = audit.record(
        db.conn,
        action="question.create",
        actor="alice",
        question_id=qid,
        details={"request_id": "req_test"},
    )
    db.conn.execute("COMMIT")

    row = db.conn.execute("SELECT * FROM audit_log WHERE audit_id = ?", (audit_id,)).fetchone()
    payload = build_event_payload(db.conn, row)
    assert payload is not None
    # SPEC §10.2: every event carries these five top-level keys.
    assert payload["action"] == "created"
    assert payload["actor"] == "alice"
    assert payload["audit_id"] == audit_id
    assert payload["occurred_at"]
    assert payload["question"]["question_id"] == qid


async def test_build_event_payload_response_includes_response(
    app, stub_session, seed_questions, seed_response
):
    [qid] = seed_questions(app, count=1)
    rid = seed_response(app, question_id=qid, voter="alice", value="+1", is_binding=True)
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    audit_id = audit.record(
        db.conn,
        action="question.respond",
        actor="alice",
        question_id=qid,
        response_id=rid,
    )
    db.conn.execute("COMMIT")
    row = db.conn.execute("SELECT * FROM audit_log WHERE audit_id = ?", (audit_id,)).fetchone()

    payload = build_event_payload(db.conn, row)
    assert payload is not None
    assert payload["action"] == "response"
    assert payload["response"]["response_id"] == rid
    assert payload["response"]["voter"] == "alice"
    assert payload["response"]["is_binding"] is True


async def test_build_event_payload_resolved_includes_tally_and_permalink(
    app, stub_session, seed_questions
):
    [qid] = seed_questions(app, count=1)
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    aid = audit.record(
        db.conn,
        action="question.resolve",
        actor="alice",
        question_id=qid,
        details={
            "outcome": "approved",
            "permalink": "/api/resolution/1",
            "tally": {"approval_type": "majority_approval", "binding_voters": []},
        },
    )
    db.conn.execute("COMMIT")
    row = db.conn.execute("SELECT * FROM audit_log WHERE audit_id = ?", (aid,)).fetchone()
    payload = build_event_payload(db.conn, row)
    assert payload is not None
    assert payload["action"] == "resolved"
    assert payload["permalink"] == "/api/resolution/1"
    assert payload["tally"]["approval_type"] == "majority_approval"


async def test_build_event_payload_edited_includes_diff(app, stub_session, seed_questions):
    [qid] = seed_questions(app, count=1)
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    aid = audit.record(
        db.conn,
        action="question.edit",
        actor="alice",
        question_id=qid,
        details={"diff": {"title": {"before": "old", "after": "new"}}},
    )
    db.conn.execute("COMMIT")
    row = db.conn.execute("SELECT * FROM audit_log WHERE audit_id = ?", (aid,)).fetchone()
    payload = build_event_payload(db.conn, row)
    assert payload is not None
    assert payload["action"] == "edited"
    assert payload["diff"]["title"]["after"] == "new"


async def test_build_event_payload_pii_exclusion(app, stub_session, seed_questions):
    """The serializer must NEVER include request-time PII (SPEC §10.3).

    The serializer reads only from persisted SQLite rows; this test asserts
    that even when ``occurred_at`` and the rest of the payload are dumped,
    there is no IP address, no cookie, no email, and no real-name field
    leaking out alongside the structured data.
    """
    [qid] = seed_questions(app, count=1)
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    aid = audit.record(
        db.conn,
        action="question.create",
        actor="alice",
        question_id=qid,
        details={"request_id": "r1"},
    )
    db.conn.execute("COMMIT")
    row = db.conn.execute("SELECT * FROM audit_log WHERE audit_id = ?", (aid,)).fetchone()
    payload = build_event_payload(db.conn, row)
    assert payload is not None

    text = json.dumps(payload).lower()
    for forbidden in ("x-forwarded-for", "cookie", "session", "email", "@apache"):
        assert forbidden not in text, (
            f"pubsub payload leaked field containing {forbidden!r}: {payload}"
        )
    # Top-level keys are a closed set.
    assert set(payload.keys()) <= {
        "action",
        "question",
        "actor",
        "occurred_at",
        "audit_id",
        "response",
        "tally",
        "permalink",
        "diff",
    }


# ---------------------------------------------------------------------------
# End-to-end publisher behavior
# ---------------------------------------------------------------------------


async def test_publisher_publishes_pending_events_and_advances_cursor(
    app, stub_session, seed_questions, tmp_db_path
):
    [qid] = seed_questions(app, count=1, project_id="seapony")
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    audit.record(db.conn, action="question.create", actor="alice", question_id=qid)
    db.conn.execute("COMMIT")

    sender = FakeSender()
    publisher = PubsubPublisher(db, _settings_with(tmp_db_path), send=sender)
    await _process_until_done(publisher)

    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert call["url"] == f"https://pubsub.example/cap/question/created/seapony/{qid}"
    assert call["payload"]["action"] == "created"
    assert call["headers"] == {}  # no auth header without credentials
    assert read_cursor(db.conn) == 1


async def test_publisher_private_event_uses_private_prefix(
    app, stub_session, seed_questions, tmp_db_path
):
    [qid] = seed_questions(app, count=1, project_id="infra", is_private=1)
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    audit.record(db.conn, action="question.create", actor="alice", question_id=qid)
    db.conn.execute("COMMIT")

    settings = _settings_with(
        tmp_db_path,
        basic_auth=PubsubBasicAuth(username="cap-publisher", password="secret"),
    )
    sender = FakeSender()
    publisher = PubsubPublisher(db, settings, send=sender)
    await _process_until_done(publisher)

    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert "/private/question/created/infra/" in call["url"]
    # Basic-auth header is set when credentials are configured.
    assert call["headers"].get("Authorization", "").startswith("Basic ")


async def test_publisher_skips_private_event_without_credentials(
    app, stub_session, seed_questions, tmp_db_path, caplog
):
    [qid] = seed_questions(app, count=1, project_id="infra", is_private=1)
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    audit.record(db.conn, action="question.create", actor="alice", question_id=qid)
    db.conn.execute("COMMIT")

    sender = FakeSender()
    publisher = PubsubPublisher(db, _settings_with(tmp_db_path), send=sender)
    caplog.set_level("WARNING")
    await _process_until_done(publisher)

    # No POST issued, but the cursor still advanced past the row (§10.4).
    assert sender.calls == []
    assert read_cursor(db.conn) == 1
    assert any("private" in rec.message.lower() for rec in caplog.records)


async def test_publisher_does_not_advance_cursor_on_failure(
    app, stub_session, seed_questions, tmp_db_path
):
    [qid] = seed_questions(app, count=1, project_id="seapony")
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    audit.record(db.conn, action="question.create", actor="alice", question_id=qid)
    db.conn.execute("COMMIT")

    sender = FakeSender(return_status=503)
    publisher = PubsubPublisher(db, _settings_with(tmp_db_path), send=sender)
    progressed = await publisher._process_batch()
    assert progressed is False
    assert len(sender.calls) == 1
    # Cursor still at 0: the failing row will be retried on the next loop.
    assert read_cursor(db.conn) == 0


async def test_publisher_recovers_after_failure(app, stub_session, seed_questions, tmp_db_path):
    [qid] = seed_questions(app, count=1)
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    audit.record(db.conn, action="question.create", actor="alice", question_id=qid)
    db.conn.execute("COMMIT")

    sender = FakeSender(return_status=503)
    publisher = PubsubPublisher(db, _settings_with(tmp_db_path), send=sender)
    assert await publisher._process_batch() is False
    assert read_cursor(db.conn) == 0

    # pypubsub recovers; same row succeeds on retry.
    sender.return_status = 200
    assert await publisher._process_batch() is True
    assert read_cursor(db.conn) == 1
    assert len(sender.calls) == 2  # one failed POST + one successful retry


async def test_publisher_processes_events_in_audit_id_order(
    app, stub_session, seed_questions, tmp_db_path
):
    [qid1, qid2] = seed_questions(app, count=2)
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    audit.record(db.conn, action="question.create", actor="a", question_id=qid1)
    audit.record(db.conn, action="question.create", actor="b", question_id=qid2)
    audit.record(
        db.conn,
        action="question.edit",
        actor="a",
        question_id=qid1,
        details={"diff": {"title": {"before": "x", "after": "y"}}},
    )
    db.conn.execute("COMMIT")

    sender = FakeSender()
    publisher = PubsubPublisher(db, _settings_with(tmp_db_path), send=sender)
    await _process_until_done(publisher)

    actions = [call["payload"]["action"] for call in sender.calls]
    audit_ids = [call["payload"]["audit_id"] for call in sender.calls]
    assert actions == ["created", "created", "edited"]
    assert audit_ids == sorted(audit_ids)


async def test_publisher_skips_unknown_audit_action(app, stub_session, seed_questions, tmp_db_path):
    # Insert a row with an action the publisher does not map. The
    # CHECK constraint on audit_log forbids unknown actions, so simulate
    # by inserting a row with a NULL question_id (which the payload builder
    # also treats as "skip and advance").
    [qid] = seed_questions(app, count=1)
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    db.conn.execute(
        """
        INSERT INTO audit_log (occurred_at, actor, action, question_id, response_id, details_json)
        VALUES (?, ?, ?, NULL, NULL, '{}')
        """,
        (
            datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "system",
            "question.create",
        ),
    )
    db.conn.execute("COMMIT")

    sender = FakeSender()
    publisher = PubsubPublisher(db, _settings_with(tmp_db_path), send=sender)
    await _process_until_done(publisher)

    # The row was skipped (no question_id), but the cursor advanced.
    assert sender.calls == []
    assert read_cursor(db.conn) == 1


async def test_publisher_treats_send_exception_as_transient(
    app, stub_session, seed_questions, tmp_db_path
):
    [qid] = seed_questions(app, count=1)
    db = app.extensions["cap_db"]
    db.conn.execute("BEGIN IMMEDIATE")
    audit.record(db.conn, action="question.create", actor="alice", question_id=qid)
    db.conn.execute("COMMIT")

    sender = FakeSender(raise_exc=RuntimeError("network blip"))
    publisher = PubsubPublisher(db, _settings_with(tmp_db_path), send=sender)
    assert await publisher._process_batch() is False
    assert read_cursor(db.conn) == 0


async def test_publisher_disabled_does_not_start(tmp_db_path):
    """start() is a no-op when settings.pubsub.enabled is false."""
    from cap_backend.db import Database

    db = Database(tmp_db_path)
    settings = _settings_with(tmp_db_path, enabled=False)
    publisher = PubsubPublisher(db, settings, send=FakeSender())
    await publisher.start()
    try:
        assert publisher.is_running() is False
    finally:
        await publisher.stop()
        db.close()


# ---------------------------------------------------------------------------
# End-to-end: real route + publisher round trip
# ---------------------------------------------------------------------------


async def test_publisher_consumes_audit_rows_written_by_question_route(
    app, stub_session, captured_emails, tmp_db_path
):
    """A POST /question creates an audit row that the publisher then emits."""
    client = app.test_client()
    body = {
        "project_id": "seapony",
        "title": "Pubsub roundtrip",
        "description": "...",
        "target_audience": "PMC: Apache SeaPony",
        "approval_type": "majority_approval",
        "is_binding": True,
        "is_private": False,
        "response_option": {"kind": "vote"},
        "closes_at": "2026-12-31T00:00:00Z",
    }
    create = await client.post("/api/question", json=body)
    assert create.status_code == 201
    qid = (await create.get_json())["question_id"]

    db = app.extensions["cap_db"]
    sender = FakeSender()
    publisher = PubsubPublisher(db, _settings_with(tmp_db_path), send=sender)
    await _process_until_done(publisher)

    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert call["payload"]["action"] == "created"
    assert call["payload"]["question"]["question_id"] == qid
    assert call["payload"]["actor"] == "alice"
    assert call["url"].endswith(f"/question/created/seapony/{qid}")
