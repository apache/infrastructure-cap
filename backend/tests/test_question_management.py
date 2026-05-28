"""Integration tests for the question-management endpoints (SPEC §9.2-§9.6).

Each test exercises one endpoint end-to-end and asserts the three things
the spec requires every state change to produce:

1. The expected HTTP response.
2. A matching audit-log row written in the same transaction.
3. A notification email sent to the project mailing list (dev@ for public
   questions, private@ for private ones), from the fixed CAP sender.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from cap_backend.auth import AuthenticatedUser

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _create_body(**overrides):
    body = {
        "project_id": "seapony",
        "title": "Sample question",
        "description": "Description body",
        "target_audience": "PMC: Apache SeaPony",
        "approval_type": "majority_approval",
        "is_binding": True,
        "is_private": False,
        "response_option": {"kind": "vote"},
        "closes_at": "2026-12-31T00:00:00Z",
    }
    body.update(overrides)
    return body


def _audit_rows(app, *, question_id: int | None = None) -> list[dict]:
    db = app.extensions["cap_db"]
    if question_id is None:
        cur = db.conn.execute("SELECT * FROM audit_log ORDER BY audit_id")
    else:
        cur = db.conn.execute(
            "SELECT * FROM audit_log WHERE question_id = ? ORDER BY audit_id",
            (question_id,),
        )
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# POST /question
# ---------------------------------------------------------------------------


async def test_create_question_happy_path(app, stub_session, captured_emails):
    client = app.test_client()
    response = await client.post("/api/question", json=_create_body())
    assert response.status_code == 201
    body = await response.get_json()
    assert body["question_id"] == 1
    assert body["status"] == "open"
    assert body["requester"] == "alice"
    assert response.headers["Location"] == "/api/question/1"

    audit = _audit_rows(app, question_id=1)
    assert len(audit) == 1
    assert audit[0]["action"] == "question.create"
    assert audit[0]["actor"] == "alice"

    assert len(captured_emails) == 1
    mail = captured_emails[0]
    assert mail["sender"] == "ASF Contingent Approval Platform <root-asfcap@apache.org>"
    assert mail["recipient"] == "dev@seapony.apache.org"
    assert "Sample question" in mail["subject"]
    assert mail["thread_start"] is True


async def test_create_private_question_uses_private_list(app, stub_session, captured_emails):
    client = app.test_client()
    response = await client.post("/api/question", json=_create_body(is_private=True))
    assert response.status_code == 201
    assert captured_emails[0]["recipient"] == "private@seapony.apache.org"


async def test_create_question_forbidden_for_non_committee(app, as_user, captured_emails):
    as_user(AuthenticatedUser(uid="bob", committees=("other",)))
    client = app.test_client()
    response = await client.post("/api/question", json=_create_body())
    assert response.status_code == 403
    body = await response.get_json()
    assert body["error"] == "not_committee_member"

    assert _audit_rows(app) == []
    assert captured_emails == []


async def test_create_question_root_can_file_for_any_project(app, as_user, captured_emails):
    as_user(AuthenticatedUser(uid="root", committees=(), is_root=True))
    client = app.test_client()
    response = await client.post(
        "/api/question",
        json=_create_body(project_id="anyproject"),
    )
    assert response.status_code == 201


async def test_create_question_rejects_extra_fields(app, stub_session):
    client = app.test_client()
    response = await client.post("/api/question", json=_create_body(question_id=99))
    # quart-schema rejects unknown fields per the extra="forbid" pydantic model.
    assert response.status_code in (400, 422)


async def test_create_question_unauthenticated(app, captured_emails):
    client = app.test_client()
    response = await client.post(
        "/api/question",
        json=_create_body(),
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /question/{id}
# ---------------------------------------------------------------------------


async def test_get_question_returns_detail(app, stub_session, seed_questions, seed_response):
    [qid] = seed_questions(app, count=1)
    seed_response(app, question_id=qid, voter="dave", value="+1")
    seed_response(app, question_id=qid, voter="erin", value="-1", comment="nope")

    client = app.test_client()
    response = await client.get(f"/api/question/{qid}")
    assert response.status_code == 200
    body = await response.get_json()
    assert body["question"]["question_id"] == qid
    assert len(body["responses"]) == 2
    assert {r["voter"] for r in body["responses"]} == {"dave", "erin"}


async def test_get_question_returns_404_for_unknown_id(app, stub_session):
    client = app.test_client()
    response = await client.get("/api/question/99999")
    assert response.status_code == 404


async def test_get_private_question_hidden_as_404(app, as_user, seed_questions):
    as_user(AuthenticatedUser(uid="outsider", committees=("other",)))
    [qid] = seed_questions(app, count=1, project_id="seapony", is_private=1)
    client = app.test_client()
    response = await client.get(f"/api/question/{qid}")
    assert response.status_code == 404, "Private question must masquerade as 404"


async def test_get_public_question_visible_to_anonymous(app, seed_questions, seed_response):
    """Anonymous callers may read public question detail (SPA read-only mode)."""
    [qid] = seed_questions(app, count=1, project_id="seapony", is_private=0)
    seed_response(app, question_id=qid, voter="dave", value="+1")
    client = app.test_client()
    response = await client.get(f"/api/question/{qid}")
    assert response.status_code == 200
    body = await response.get_json()
    assert body["question"]["question_id"] == qid
    # viewer_is_binding is always False for an anonymous viewer (no committees).
    assert body["question"]["viewer_is_binding"] is False
    # Responses are surfaced verbatim so the read-only UI can render them.
    assert len(body["responses"]) == 1


async def test_get_private_question_hidden_from_anonymous(app, seed_questions):
    [qid] = seed_questions(app, count=1, project_id="seapony", is_private=1)
    client = app.test_client()
    response = await client.get(f"/api/question/{qid}")
    assert response.status_code == 404, "Private question must masquerade as 404 for anonymous"


# ---------------------------------------------------------------------------
# PATCH /question/{id}
# ---------------------------------------------------------------------------


async def test_patch_question_by_requester(app, stub_session, seed_questions, captured_emails):
    [qid] = seed_questions(app, count=1, requester="alice")
    client = app.test_client()
    response = await client.patch(
        f"/api/question/{qid}",
        json={"title": "Renamed", "description": "Updated body"},
    )
    assert response.status_code == 200
    body = await response.get_json()
    assert body["title"] == "Renamed"
    assert body["description"] == "Updated body"

    audit = _audit_rows(app, question_id=qid)
    assert audit[-1]["action"] == "question.edit"
    diff = json.loads(audit[-1]["details_json"])["diff"]
    assert "title" in diff
    assert diff["title"]["after"] == "Renamed"

    assert len(captured_emails) == 1
    assert captured_emails[0]["recipient"] == "dev@seapony.apache.org"
    assert "updated" in captured_emails[0]["subject"].lower()


async def test_patch_question_forbidden_for_other_user(app, as_user, seed_questions):
    as_user(AuthenticatedUser(uid="bob", committees=("seapony",)))
    [qid] = seed_questions(app, count=1, requester="alice")
    client = app.test_client()
    response = await client.patch(f"/api/question/{qid}", json={"title": "Hostile"})
    assert response.status_code == 403


async def test_patch_question_409_if_resolved(app, stub_session, seed_questions):
    [qid] = seed_questions(
        app,
        count=1,
        requester="alice",
        status="resolved",
        outcome="approved",
    )
    client = app.test_client()
    response = await client.patch(f"/api/question/{qid}", json={"title": "X"})
    assert response.status_code == 409


async def test_patch_question_root_can_edit(app, as_user, seed_questions, captured_emails):
    as_user(AuthenticatedUser(uid="root", committees=(), is_root=True))
    [qid] = seed_questions(app, count=1, requester="alice")
    client = app.test_client()
    response = await client.patch(f"/api/question/{qid}", json={"title": "Root edit"})
    assert response.status_code == 200


async def test_patch_question_no_op_skips_audit_and_email(
    app, stub_session, seed_questions, captured_emails
):
    [qid] = seed_questions(app, count=1, requester="alice", title="Same")
    client = app.test_client()
    response = await client.patch(f"/api/question/{qid}", json={"title": "Same"})
    assert response.status_code == 200
    assert _audit_rows(app, question_id=qid) == []
    assert captured_emails == []


# ---------------------------------------------------------------------------
# DELETE /question/{id}
# ---------------------------------------------------------------------------


async def test_delete_question_marks_removed(app, stub_session, seed_questions, captured_emails):
    [qid] = seed_questions(app, count=1, requester="alice")
    client = app.test_client()
    response = await client.delete(f"/api/question/{qid}")
    assert response.status_code == 204
    assert (await response.get_data()) == b""

    db = app.extensions["cap_db"]
    row = db.conn.execute(
        "SELECT status, outcome FROM questions WHERE question_id = ?", (qid,)
    ).fetchone()
    assert row["status"] == "removed"
    assert row["outcome"] == "withdrawn"

    audit = _audit_rows(app, question_id=qid)
    assert audit[-1]["action"] == "question.remove"

    assert len(captured_emails) == 1
    assert captured_emails[0]["recipient"] == "dev@seapony.apache.org"
    assert "withdrawn" in captured_emails[0]["subject"].lower()


async def test_delete_question_forbidden_for_other_user(app, as_user, seed_questions):
    as_user(AuthenticatedUser(uid="bob", committees=("seapony",)))
    [qid] = seed_questions(app, count=1, requester="alice")
    client = app.test_client()
    response = await client.delete(f"/api/question/{qid}")
    assert response.status_code == 403


async def test_delete_question_409_if_already_removed(app, stub_session, seed_questions):
    [qid] = seed_questions(
        app,
        count=1,
        requester="alice",
        status="removed",
        outcome="withdrawn",
    )
    client = app.test_client()
    response = await client.delete(f"/api/question/{qid}")
    assert response.status_code == 409


async def test_delete_private_question_uses_private_list(
    app, stub_session, seed_questions, captured_emails
):
    [qid] = seed_questions(app, count=1, requester="alice", is_private=1)
    client = app.test_client()
    response = await client.delete(f"/api/question/{qid}")
    assert response.status_code == 204
    assert captured_emails[0]["recipient"] == "private@seapony.apache.org"


# ---------------------------------------------------------------------------
# POST /question/{id}/resolve
# ---------------------------------------------------------------------------


def _past_iso(minutes: int = 5) -> str:
    return (
        (datetime.now(UTC) - timedelta(minutes=minutes))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


async def test_resolve_question_after_deadline_marks_outcome(
    app, stub_session, seed_questions, seed_response, captured_emails
):
    [qid] = seed_questions(
        app,
        count=1,
        requester="alice",
        approval_type="majority_approval",
        closes_at=_past_iso(10),
    )
    seed_response(app, question_id=qid, voter="dave", value="+1", is_binding=True)
    seed_response(app, question_id=qid, voter="erin", value="+1", is_binding=True)
    seed_response(app, question_id=qid, voter="frank", value="+1", is_binding=True)

    client = app.test_client()
    response = await client.post(f"/api/question/{qid}/resolve")
    assert response.status_code == 200
    body = await response.get_json()
    assert body["status"] == "resolved"
    assert body["outcome"] == "approved"
    assert body["permalink"].endswith(f"/api/resolution/{qid}")

    audit = _audit_rows(app, question_id=qid)
    assert audit[-1]["action"] == "question.resolve"
    details = json.loads(audit[-1]["details_json"])
    assert details["outcome"] == "approved"
    assert "tally" in details

    assert captured_emails
    mail = captured_emails[-1]
    assert "resolved" in mail["subject"].lower()
    assert "approved" in mail["message"].lower()


async def test_resolve_idempotent_for_already_resolved(app, stub_session, seed_questions):
    [qid] = seed_questions(
        app,
        count=1,
        requester="alice",
        status="resolved",
        outcome="approved",
        permalink="/api/resolution/1",
    )
    client = app.test_client()
    response = await client.post(f"/api/question/{qid}/resolve")
    assert response.status_code == 200
    body = await response.get_json()
    assert body["status"] == "resolved"
    # No new audit row, no new email.
    assert _audit_rows(app, question_id=qid) == []


async def test_resolve_before_deadline_forbidden_for_non_root(app, stub_session, seed_questions):
    # closes_at is 3 days in the future (the default in seed_questions).
    [qid] = seed_questions(app, count=1, requester="alice")
    client = app.test_client()
    response = await client.post(f"/api/question/{qid}/resolve")
    assert response.status_code == 403


async def test_resolve_before_deadline_root_override(app, as_user, seed_questions, captured_emails):
    as_user(AuthenticatedUser(uid="root", committees=(), is_root=True))
    [qid] = seed_questions(app, count=1, requester="alice")
    client = app.test_client()
    response = await client.post(f"/api/question/{qid}/resolve")
    assert response.status_code == 200
    body = await response.get_json()
    assert body["status"] == "resolved"


async def test_resolve_unanimous_with_active_veto(app, stub_session, seed_questions, seed_response):
    [qid] = seed_questions(
        app,
        count=1,
        requester="alice",
        approval_type="unanimous_approval",
        closes_at=_past_iso(),
    )
    seed_response(app, question_id=qid, voter="dave", value="+1", is_binding=True)
    seed_response(
        app,
        question_id=qid,
        voter="erin",
        value="-1",
        comment="hold on",
        is_binding=True,
        is_veto=True,
    )
    client = app.test_client()
    response = await client.post(f"/api/question/{qid}/resolve")
    assert response.status_code == 200
    body = await response.get_json()
    assert body["outcome"] == "vetoed"


async def test_resolve_unanimous_with_withdrawn_veto(
    app, stub_session, seed_questions, seed_response
):
    [qid] = seed_questions(
        app,
        count=1,
        requester="alice",
        approval_type="unanimous_approval",
        closes_at=_past_iso(),
    )
    earlier = datetime.now(UTC) - timedelta(minutes=30)
    later = datetime.now(UTC) - timedelta(minutes=10)
    seed_response(
        app,
        question_id=qid,
        voter="erin",
        value="-1",
        comment="hold on",
        is_binding=True,
        is_veto=True,
        created_at=earlier,
    )
    # Same voter later submits a non-veto vote: the veto is withdrawn.
    seed_response(
        app,
        question_id=qid,
        voter="erin",
        value="+1",
        is_binding=True,
        is_veto=False,
        created_at=later,
    )
    # Two additional binding +1 votes so the question clears the
    # minimum-three binding +1 floor required for unanimous_approval.
    seed_response(app, question_id=qid, voter="dave", value="+1", is_binding=True)
    seed_response(app, question_id=qid, voter="frank", value="+1", is_binding=True)
    client = app.test_client()
    response = await client.post(f"/api/question/{qid}/resolve")
    body = await response.get_json()
    assert body["outcome"] == "approved", body


async def test_resolve_unanimous_insufficient_binding_plus_ones(
    app, stub_session, seed_questions, seed_response
):
    """Unanimous approval needs >= 3 binding +1 votes even without a veto."""
    [qid] = seed_questions(
        app,
        count=1,
        requester="alice",
        approval_type="unanimous_approval",
        closes_at=_past_iso(),
    )
    seed_response(app, question_id=qid, voter="dave", value="+1", is_binding=True)
    seed_response(app, question_id=qid, voter="erin", value="+1", is_binding=True)
    client = app.test_client()
    response = await client.post(f"/api/question/{qid}/resolve")
    body = await response.get_json()
    assert body["outcome"] == "insufficient_votes", body


async def test_resolve_majority_insufficient_binding_plus_ones(
    app, stub_session, seed_questions, seed_response
):
    """Majority approval needs >= 3 binding +1 votes."""
    [qid] = seed_questions(
        app,
        count=1,
        requester="alice",
        approval_type="majority_approval",
        closes_at=_past_iso(),
    )
    seed_response(app, question_id=qid, voter="dave", value="+1", is_binding=True)
    seed_response(app, question_id=qid, voter="erin", value="+1", is_binding=True)
    client = app.test_client()
    response = await client.post(f"/api/question/{qid}/resolve")
    body = await response.get_json()
    assert body["outcome"] == "insufficient_votes", body


async def test_resolve_lazy_consensus_blocked_by_objection(
    app, stub_session, seed_questions, seed_response
):
    [qid] = seed_questions(
        app,
        count=1,
        requester="alice",
        approval_type="lazy_consensus",
        closes_at=_past_iso(),
    )
    seed_response(
        app,
        question_id=qid,
        voter="dave",
        kind="lazy_consensus",
        objection=True,
        comment="nope",
    )
    client = app.test_client()
    response = await client.post(f"/api/question/{qid}/resolve")
    body = await response.get_json()
    assert body["outcome"] == "insufficient_votes"


async def test_resolve_lazy_consensus_silent_is_approved(app, stub_session, seed_questions):
    [qid] = seed_questions(
        app,
        count=1,
        requester="alice",
        approval_type="lazy_consensus",
        closes_at=_past_iso(),
    )
    client = app.test_client()
    response = await client.post(f"/api/question/{qid}/resolve")
    body = await response.get_json()
    assert body["outcome"] == "approved"


async def test_resolve_majority_no_binding_votes_is_insufficient(
    app, stub_session, seed_questions, seed_response
):
    [qid] = seed_questions(
        app,
        count=1,
        requester="alice",
        approval_type="majority_approval",
        closes_at=_past_iso(),
    )
    # Only non-binding votes cast.
    seed_response(app, question_id=qid, voter="x", value="+1", is_binding=False)
    seed_response(app, question_id=qid, voter="y", value="+1", is_binding=False)
    client = app.test_client()
    response = await client.post(f"/api/question/{qid}/resolve")
    body = await response.get_json()
    assert body["outcome"] == "insufficient_votes"


# ---------------------------------------------------------------------------
# notify module unit tests
# ---------------------------------------------------------------------------


def test_notify_recipient_public_vs_private():
    from types import SimpleNamespace

    from cap_backend.notify import recipient_for

    public = SimpleNamespace(project_id="seapony", is_private=False)
    private = SimpleNamespace(project_id="seapony", is_private=True)
    assert recipient_for(public) == "dev@seapony.apache.org"
    assert recipient_for(private) == "private@seapony.apache.org"


def test_notify_send_swallows_dispatch_failures(monkeypatch):
    """A failure inside asfpy.messaging.mail must NOT propagate.

    The audit log is the durable record; a misconfigured MSA in dev or a
    transient SMTP failure in prod must not block a state change that has
    already committed to the database.
    """
    from types import SimpleNamespace

    from cap_backend import notify

    def _explode(**kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(notify, "_send_mail", _explode)

    q = SimpleNamespace(
        project_id="seapony",
        is_private=False,
        question_id=42,
        title="x",
    )
    result = notify.send("created", q, actor="alice", body="b")
    assert result is False  # apparent failure, but no exception bubbled out
