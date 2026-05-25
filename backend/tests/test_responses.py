"""Integration tests for POST /question/{id}/responses (SPEC §9.7).

Every test asserts the three artifacts every state change is expected to
produce per the SPEC:

1. HTTP response shape and status.
2. Matching audit-log row (``question.respond``) written in the same
   transaction as the responses-table insert.
3. Notification email dispatched to the appropriate mailing list.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from cap_backend.auth import AuthenticatedUser


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


def _response_rows(app, question_id: int) -> list[dict]:
    db = app.extensions["cap_db"]
    cur = db.conn.execute(
        "SELECT * FROM responses WHERE question_id = ? ORDER BY created_at, response_id",
        (question_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def _past_iso(minutes: int = 5) -> str:
    return (
        (datetime.now(UTC) - timedelta(minutes=minutes))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_submit_vote_response_happy_path(
    app, stub_session, seed_questions, captured_emails
):
    [qid] = seed_questions(app, count=1, approval_type="majority_approval")
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "+1"},
    )
    assert response.status_code == 201
    body = await response.get_json()
    assert body["voter"] == "alice"
    assert body["question_id"] == qid
    assert body["response_kind"] == "vote"
    assert body["response"]["value"] == "+1"
    # alice is on the seapony committee per the fake_user fixture, and the
    # seeded question has is_binding=True, so the snapshot must be binding.
    assert body["is_binding"] is True
    assert body["is_veto"] is False
    assert response.headers["Location"].startswith(f"/question/{qid}/responses/")

    rows = _response_rows(app, qid)
    assert len(rows) == 1
    assert rows[0]["voter"] == "alice"

    audit = _audit_rows(app, question_id=qid)
    assert audit[-1]["action"] == "question.respond"
    assert audit[-1]["response_id"] == body["response_id"]
    details = json.loads(audit[-1]["details_json"])
    assert details["is_binding"] is True

    assert len(captured_emails) == 1
    mail = captured_emails[-1]
    assert "response" in mail["subject"].lower()
    assert mail["thread_start"] is False
    assert mail["thread_key"] == f"cap-question-{qid}"


async def test_submit_lazy_consensus_objection(
    app, stub_session, seed_questions, captured_emails
):
    [qid] = seed_questions(
        app,
        count=1,
        approval_type="lazy_consensus",
        response_option_json=json.dumps(
            {"kind": "lazy_consensus", "allow_comment": True}
        ),
    )
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "lazy_consensus", "objection": True, "comment": "concerns"},
    )
    assert response.status_code == 201
    body = await response.get_json()
    assert body["response"]["objection"] is True
    assert body["comment"] == "concerns"


async def test_submit_free_text(
    app, stub_session, seed_questions, captured_emails
):
    [qid] = seed_questions(
        app,
        count=1,
        approval_type="majority_approval",
        response_option_json=json.dumps({"kind": "free_text", "max_length": 4000}),
    )
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "free_text", "text": "hello there"},
    )
    assert response.status_code == 201
    body = await response.get_json()
    assert body["response"]["text"] == "hello there"


# ---------------------------------------------------------------------------
# Veto handling
# ---------------------------------------------------------------------------


async def test_binding_minus_one_on_unanimous_without_comment_rejected(
    app, stub_session, seed_questions, captured_emails
):
    [qid] = seed_questions(app, count=1, approval_type="unanimous_approval")
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "-1"},
    )
    assert response.status_code == 400
    body = await response.get_json()
    assert body["error"] == "missing_veto_comment"

    assert _response_rows(app, qid) == []
    assert _audit_rows(app, question_id=qid) == []
    assert captured_emails == []


async def test_binding_minus_one_on_unanimous_with_comment_is_veto(
    app, stub_session, seed_questions
):
    [qid] = seed_questions(app, count=1, approval_type="unanimous_approval")
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "-1", "comment": "tech reason"},
    )
    assert response.status_code == 201
    body = await response.get_json()
    assert body["is_veto"] is True
    assert body["is_binding"] is True


async def test_non_binding_minus_one_on_unanimous_records_no_veto(
    app, as_user, seed_questions
):
    # outsider is not on the seapony committee, so any vote they cast is
    # non-binding and (per SPEC §8.3.1) can never veto.
    as_user(AuthenticatedUser(uid="outsider", committees=("other",)))
    [qid] = seed_questions(
        app,
        count=1,
        approval_type="unanimous_approval",
        is_private=0,
    )
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "-1"},  # no comment required
    )
    assert response.status_code == 201
    body = await response.get_json()
    assert body["is_binding"] is False
    assert body["is_veto"] is False


async def test_veto_withdrawal_appends_new_row(
    app, stub_session, seed_questions
):
    [qid] = seed_questions(app, count=1, approval_type="unanimous_approval")
    client = app.test_client()
    veto = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "-1", "comment": "hold on"},
    )
    assert veto.status_code == 201
    assert (await veto.get_json())["is_veto"] is True

    # Same voter submits a non-veto vote: the latest response wins for tally,
    # but the old row is preserved (§7.2).
    withdrawn = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "+1"},
    )
    assert withdrawn.status_code == 201
    rows = _response_rows(app, qid)
    assert len(rows) == 2
    assert {r["is_veto"] for r in rows} == {0, 1}


# ---------------------------------------------------------------------------
# Compatibility with response_option
# ---------------------------------------------------------------------------


async def test_kind_mismatch_with_question_option_rejected(
    app, stub_session, seed_questions
):
    [qid] = seed_questions(
        app,
        count=1,
        approval_type="majority_approval",
        response_option_json=json.dumps(
            {"kind": "vote", "allowed_values": ["+1", "-1"], "allow_comment": True}
        ),
    )
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "free_text", "text": "nope"},
    )
    assert response.status_code == 400
    body = await response.get_json()
    assert body["error"] == "response_kind_mismatch"


async def test_vote_value_not_in_allowed_values_rejected(
    app, stub_session, seed_questions
):
    [qid] = seed_questions(
        app,
        count=1,
        response_option_json=json.dumps(
            {"kind": "vote", "allowed_values": ["+1", "-1"], "allow_comment": True}
        ),
    )
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "+0"},
    )
    assert response.status_code == 400
    body = await response.get_json()
    assert body["error"] == "value_not_allowed"


async def test_free_text_exceeding_max_length_rejected(
    app, stub_session, seed_questions
):
    [qid] = seed_questions(
        app,
        count=1,
        response_option_json=json.dumps({"kind": "free_text", "max_length": 10}),
    )
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "free_text", "text": "this is far too long for the cap"},
    )
    assert response.status_code == 400
    body = await response.get_json()
    assert body["error"] == "text_too_long"


# ---------------------------------------------------------------------------
# §7.4 lifecycle ordering
# ---------------------------------------------------------------------------


async def test_response_after_deadline_rejected_with_409(
    app, stub_session, seed_questions, captured_emails
):
    [qid] = seed_questions(app, count=1, closes_at=_past_iso(10))
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "+1"},
    )
    assert response.status_code == 409
    body = await response.get_json()
    assert body["error"] == "deadline_passed"

    # No row written; no audit; no email.
    assert _response_rows(app, qid) == []
    assert _audit_rows(app, question_id=qid) == []
    assert captured_emails == []


async def test_response_to_resolved_question_rejected_with_409(
    app, stub_session, seed_questions
):
    # Future deadline (default in seed_questions) but status already
    # resolved: SPEC §7.4 step 2 catches this case.
    [qid] = seed_questions(
        app,
        count=1,
        status="resolved",
        outcome="approved",
    )
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "+1"},
    )
    assert response.status_code == 409
    body = await response.get_json()
    assert body["error"] == "not_open"


async def test_response_to_removed_question_rejected_with_409(
    app, stub_session, seed_questions
):
    [qid] = seed_questions(
        app,
        count=1,
        status="removed",
        outcome="withdrawn",
    )
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "+1"},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Auth and ACL
# ---------------------------------------------------------------------------


async def test_response_unauthenticated(app, seed_questions, captured_emails):
    [qid] = seed_questions(app, count=1)
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "+1"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 401
    assert _response_rows(app, qid) == []


async def test_response_to_unknown_question_returns_404(app, stub_session):
    client = app.test_client()
    response = await client.post(
        "/question/99999/responses",
        json={"kind": "vote", "value": "+1"},
    )
    assert response.status_code == 404


async def test_response_to_private_question_outsider_sees_404(
    app, as_user, seed_questions
):
    as_user(AuthenticatedUser(uid="outsider", committees=("other",)))
    [qid] = seed_questions(app, count=1, project_id="seapony", is_private=1)
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "+1"},
    )
    # Per SPEC §7.5, ACL denial collapses to 404, not 403.
    assert response.status_code == 404
    assert _response_rows(app, qid) == []


# ---------------------------------------------------------------------------
# Malformed bodies
# ---------------------------------------------------------------------------


async def test_response_invalid_body_rejected(app, stub_session, seed_questions):
    [qid] = seed_questions(app, count=1)
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote"},  # missing required `value`
    )
    assert response.status_code == 400


async def test_response_unknown_kind_rejected(app, stub_session, seed_questions):
    [qid] = seed_questions(app, count=1)
    client = app.test_client()
    response = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "bogus", "value": "+1"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Routes through to /question/{id} GET
# ---------------------------------------------------------------------------


async def test_get_question_includes_submitted_response(
    app, stub_session, seed_questions, captured_emails
):
    [qid] = seed_questions(app, count=1)
    client = app.test_client()
    post = await client.post(
        f"/question/{qid}/responses",
        json={"kind": "vote", "value": "+1", "comment": "lgtm"},
    )
    assert post.status_code == 201
    new_rid = (await post.get_json())["response_id"]

    detail = await client.get(f"/question/{qid}")
    assert detail.status_code == 200
    body = await detail.get_json()
    rids = [r["response_id"] for r in body["responses"]]
    assert new_rid in rids
