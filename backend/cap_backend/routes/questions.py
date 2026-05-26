"""Question endpoints. See SPEC §9.1 through §9.6."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError
from quart import Blueprint, Response, current_app, jsonify, request
from quart_schema import document_response, validate_request, validate_response

from cap_backend import audit, dao, notify, tally
from cap_backend.auth import AuthenticatedUser, can_view_question, current_user
from cap_backend.schemas.errors import AuthenticationRequired, ErrorMessage
from cap_backend.schemas.questions import (
    CreateQuestionRequest,
    EditQuestionRequest,
    ListResponse,
    Question,
    QuestionDetail,
    StoredResponse,
)
from cap_backend.schemas.responses import SubmittedResponse

# Module-level adapter: reused across requests, validates the discriminated
# union from §8.2 (vote / lazy_consensus / free_text).
_SUBMITTED_RESPONSE_ADAPTER: TypeAdapter[Any] = TypeAdapter(SubmittedResponse)

questions_bp = Blueprint("questions", __name__)


async def _unauthenticated_response() -> tuple[Any, int]:
    return (
        jsonify({"error": "authentication_required", "login_url": "/auth"}),
        401,
    )


def _settings():
    return current_app.extensions["cap_settings"]


def _permalink_for(question_id: int) -> str:
    base = _settings().server.permalink_base or ""
    return f"{base}/resolution/{question_id}"


def _notify(event: str, question: Question, *, actor: str, body: str) -> None:
    """Best-effort send; failures are logged inside notify.send()."""
    notify.send(event=event, question=question, actor=actor, body=body)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# GET /list
# ---------------------------------------------------------------------------


@questions_bp.get("/list")
@validate_response(ListResponse, 200)
@document_response(AuthenticationRequired, 401)
async def list_pending() -> Any:
    user = await current_user()
    if user is None:
        return await _unauthenticated_response()

    db = current_app.extensions["cap_db"]
    rows = db.conn.execute(
        """
        SELECT question_id, request_id, project_id, title, description, requester,
               target_audience, approval_type, response_option_json, is_binding,
               is_private, permalink, status, outcome, closes_at, created_at, updated_at
          FROM questions
         WHERE status = 'open'
         ORDER BY closes_at ASC, question_id ASC
        """
    ).fetchall()

    now = datetime.now(UTC)
    pending: list[Question] = []
    for row in rows:
        question = dao.row_to_question(row, viewer=user, now=now)
        if not can_view_question(user, question):
            continue
        pending.append(question)

    return ListResponse(user=user.uid, pending=pending)


# ---------------------------------------------------------------------------
# POST /question
# ---------------------------------------------------------------------------


@questions_bp.post("/question")
@validate_request(CreateQuestionRequest)
@validate_response(Question, 201)
@document_response(AuthenticationRequired, 401)
@document_response(ErrorMessage, 403)
async def create_question(data: CreateQuestionRequest) -> Any:
    user = await current_user()
    if user is None:
        return await _unauthenticated_response()

    if data.project_id not in user.committees and not user.is_root:
        return jsonify({"error": "not_committee_member"}), 403

    # request_id is server-assigned (SPEC §9.2): clients cannot supply it,
    # and the UNIQUE constraint on questions.request_id guarantees no row
    # ever shares an id with another.
    request_id = str(uuid.uuid4())

    db = current_app.extensions["cap_db"]
    async with db.write_lock:
        try:
            db.conn.execute("BEGIN IMMEDIATE")
            question_id = dao.insert_question(
                db.conn,
                request_id=request_id,
                project_id=data.project_id,
                title=data.title,
                description=data.description,
                requester=user.uid,
                target_audience=data.target_audience,
                approval_type=data.approval_type,
                response_option=data.response_option.model_dump(),
                is_binding=data.is_binding,
                is_private=data.is_private,
                closes_at=data.closes_at,
            )
            audit.record(
                db.conn,
                action="question.create",
                actor=user.uid,
                question_id=question_id,
                details={"request_id": request_id, "project_id": data.project_id},
            )
            db.conn.execute("COMMIT")
        except Exception:
            db.conn.execute("ROLLBACK")
            raise

    row = dao.fetch_question_row(db.conn, question_id)
    assert row is not None
    question = dao.row_to_question(row, viewer=user)

    _notify(
        "created",
        question,
        actor=user.uid,
        body=(
            f"A new contingent-approval question has been opened.\n"
            f"\n"
            f"Title:        {question.title}\n"
            f"Approval:     {question.approval_type}\n"
            f"Closes at:    {question.closes_at.isoformat()}\n"
            f"Description:\n"
            f"{question.description}\n"
        ),
    )
    return question, 201, {"Location": f"/question/{question_id}"}


# ---------------------------------------------------------------------------
# GET /question/<id>
# ---------------------------------------------------------------------------


@questions_bp.get("/question/<int:question_id>")
@validate_response(QuestionDetail, 200)
@document_response(AuthenticationRequired, 401)
@document_response(ErrorMessage, 404)
async def get_question(question_id: int) -> Any:
    user = await current_user()
    if user is None:
        return await _unauthenticated_response()

    db = current_app.extensions["cap_db"]
    row = dao.fetch_question_row(db.conn, question_id)
    if row is None:
        return jsonify({"error": "not_found"}), 404

    question = dao.row_to_question(row, viewer=user)
    if not can_view_question(user, question):
        return jsonify({"error": "not_found"}), 404

    response_rows = dao.fetch_all_response_rows(db.conn, question_id)
    responses = [dao.row_to_stored_response(r) for r in response_rows]
    return QuestionDetail(question=question, responses=responses)


# ---------------------------------------------------------------------------
# PATCH /question/<id>
# ---------------------------------------------------------------------------


@questions_bp.patch("/question/<int:question_id>")
@validate_request(EditQuestionRequest)
@validate_response(Question, 200)
@document_response(AuthenticationRequired, 401)
@document_response(ErrorMessage, 403)
@document_response(ErrorMessage, 404)
@document_response(ErrorMessage, 409)
async def edit_question(data: EditQuestionRequest, question_id: int) -> Any:
    user = await current_user()
    if user is None:
        return await _unauthenticated_response()

    db = current_app.extensions["cap_db"]
    row = dao.fetch_question_row(db.conn, question_id)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    question = dao.row_to_question(row, viewer=user)
    if not can_view_question(user, question):
        return jsonify({"error": "not_found"}), 404

    if row["requester"] != user.uid and not user.is_root:
        return jsonify({"error": "forbidden"}), 403
    if row["status"] != "open":
        return jsonify({"error": "not_open", "status": row["status"]}), 409

    edits = data.model_dump(exclude_none=True)
    async with db.write_lock:
        try:
            db.conn.execute("BEGIN IMMEDIATE")
            diff = dao.apply_edits(
                db.conn,
                question_id=question_id,
                current_row=row,
                edits=edits,
            )
            if diff:
                audit.record(
                    db.conn,
                    action="question.edit",
                    actor=user.uid,
                    question_id=question_id,
                    details={"diff": diff},
                )
            db.conn.execute("COMMIT")
        except Exception:
            db.conn.execute("ROLLBACK")
            raise

    updated_row = dao.fetch_question_row(db.conn, question_id)
    assert updated_row is not None
    updated = dao.row_to_question(updated_row, viewer=user)

    if diff:
        changed = ", ".join(sorted(diff.keys()))
        _notify(
            "edited",
            updated,
            actor=user.uid,
            body=(
                f"The following fields were changed: {changed}.\n"
                f"\n"
                f"Title:     {updated.title}\n"
                f"Closes at: {updated.closes_at.isoformat()}\n"
            ),
        )
    return updated


# ---------------------------------------------------------------------------
# DELETE /question/<id>
# ---------------------------------------------------------------------------


@questions_bp.delete("/question/<int:question_id>")
@document_response(AuthenticationRequired, 401)
@document_response(ErrorMessage, 403)
@document_response(ErrorMessage, 404)
@document_response(ErrorMessage, 409)
async def remove_question(question_id: int) -> Any:
    user = await current_user()
    if user is None:
        return await _unauthenticated_response()

    db = current_app.extensions["cap_db"]
    row = dao.fetch_question_row(db.conn, question_id)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    question = dao.row_to_question(row, viewer=user)
    if not can_view_question(user, question):
        return jsonify({"error": "not_found"}), 404

    if row["requester"] != user.uid and not user.is_root:
        return jsonify({"error": "forbidden"}), 403
    if row["status"] != "open":
        return jsonify({"error": "not_open", "status": row["status"]}), 409

    async with db.write_lock:
        try:
            db.conn.execute("BEGIN IMMEDIATE")
            dao.mark_removed(db.conn, question_id)
            audit.record(
                db.conn,
                action="question.remove",
                actor=user.uid,
                question_id=question_id,
                details={},
            )
            db.conn.execute("COMMIT")
        except Exception:
            db.conn.execute("ROLLBACK")
            raise

    fresh_row = dao.fetch_question_row(db.conn, question_id)
    assert fresh_row is not None
    fresh = dao.row_to_question(fresh_row, viewer=user)
    _notify(
        "closed",
        fresh,
        actor=user.uid,
        body=f"Question #{question_id} was withdrawn by {user.uid} before the deadline.\n",
    )
    return Response("", status=204)


# ---------------------------------------------------------------------------
# POST /question/<id>/resolve
# ---------------------------------------------------------------------------


@questions_bp.post("/question/<int:question_id>/resolve")
@validate_response(Question, 200)
@document_response(AuthenticationRequired, 401)
@document_response(ErrorMessage, 403)
@document_response(ErrorMessage, 404)
async def resolve_question(question_id: int) -> Any:
    user = await current_user()
    if user is None:
        return await _unauthenticated_response()

    db = current_app.extensions["cap_db"]
    row = dao.fetch_question_row(db.conn, question_id)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    question = dao.row_to_question(row, viewer=user)
    if not can_view_question(user, question):
        return jsonify({"error": "not_found"}), 404

    if row["requester"] != user.uid and not user.is_root:
        return jsonify({"error": "forbidden"}), 403

    # Idempotent: already-resolved questions return the existing record.
    if row["status"] != "open":
        return question

    # Early resolution (before closes_at) is reserved for root.
    now = datetime.now(UTC)
    closes_at = question.closes_at
    if now < closes_at and not user.is_root:
        return (
            jsonify(
                {
                    "error": "deadline_in_future",
                    "closes_at": closes_at.isoformat(),
                }
            ),
            403,
        )

    permalink = _permalink_for(question_id)

    async with db.write_lock:
        try:
            db.conn.execute("BEGIN IMMEDIATE")
            response_rows = dao.fetch_all_response_rows(db.conn, question_id)
            outcome, tally_payload = tally.compute_outcome(row, response_rows)
            dao.mark_resolved(
                db.conn,
                question_id=question_id,
                outcome=outcome,
                permalink=permalink,
            )
            audit.record(
                db.conn,
                action="question.resolve",
                actor=user.uid,
                question_id=question_id,
                details={
                    "outcome": outcome,
                    "permalink": permalink,
                    "tally": tally_payload,
                },
            )
            db.conn.execute("COMMIT")
        except Exception:
            db.conn.execute("ROLLBACK")
            raise

    final_row = dao.fetch_question_row(db.conn, question_id)
    assert final_row is not None
    final = dao.row_to_question(final_row, viewer=user)
    _notify(
        "resolved",
        final,
        actor=user.uid,
        body=(
            f"Question #{question_id} has been resolved.\n"
            f"\n"
            f"Outcome:   {outcome}\n"
            f"Permalink: {permalink}\n"
        ),
    )
    return final


# ---------------------------------------------------------------------------
# POST /question/<id>/responses
# ---------------------------------------------------------------------------


def _summarize_response(
    submitted: Any,
    *,
    voter: str,
    is_binding: bool,
    is_veto: bool,
) -> str:
    binding_chip = "binding" if is_binding else "non-binding"
    if submitted.kind == "vote":
        line = f"{voter} ({binding_chip}) voted {submitted.value}"
        if is_veto:
            line = f"{voter} (binding) VETOED with -1"
        if submitted.comment:
            line += f"\n\nComment:\n{submitted.comment}"
        return line
    if submitted.kind == "lazy_consensus":
        verb = "objected" if submitted.objection else "did not object"
        line = f"{voter} ({binding_chip}) {verb}"
        if submitted.comment:
            line += f"\n\nComment:\n{submitted.comment}"
        return line
    excerpt = submitted.text.strip().splitlines()[0] if submitted.text else ""
    if len(excerpt) > 200:
        excerpt = excerpt[:197] + "..."
    return f"{voter} ({binding_chip}) responded:\n\n{excerpt}"


@questions_bp.post("/question/<int:question_id>/responses")
@validate_response(StoredResponse, 201)
@document_response(AuthenticationRequired, 401)
@document_response(ErrorMessage, 400)
@document_response(ErrorMessage, 404)
@document_response(ErrorMessage, 409)
async def submit_response(question_id: int) -> Any:
    """Submit a new response, or amend the caller's previous response.

    See SPEC §9.7. Acceptance order (§7.4): deadline first, then status.
    """
    user = await current_user()
    if user is None:
        return await _unauthenticated_response()

    raw = await request.get_json(silent=True)
    if not isinstance(raw, dict):
        return jsonify({"error": "invalid_body"}), 400
    try:
        submitted = _SUBMITTED_RESPONSE_ADAPTER.validate_python(raw)
    except ValidationError as exc:
        return jsonify({"error": "invalid_body", "details": exc.errors()}), 400

    db = current_app.extensions["cap_db"]
    row = dao.fetch_question_row(db.conn, question_id)
    if row is None:
        return jsonify({"error": "not_found"}), 404
    question = dao.row_to_question(row, viewer=user)
    if not can_view_question(user, question):
        # Private-question ACL collapses to 404 (§7.5).
        return jsonify({"error": "not_found"}), 404

    # The submitted response must match the question's response_option (§8.2).
    response_option = question.response_option
    if submitted.kind != response_option.kind:
        return (
            jsonify(
                {
                    "error": "response_kind_mismatch",
                    "expected": response_option.kind,
                    "got": submitted.kind,
                }
            ),
            400,
        )
    if submitted.kind == "vote" and submitted.value not in response_option.allowed_values:
        return (
            jsonify(
                {
                    "error": "value_not_allowed",
                    "value": submitted.value,
                    "allowed": list(response_option.allowed_values),
                }
            ),
            400,
        )
    if submitted.kind == "free_text" and len(submitted.text) > response_option.max_length:
        return (
            jsonify(
                {
                    "error": "text_too_long",
                    "max_length": response_option.max_length,
                }
            ),
            400,
        )

    # is_binding is the snapshot the resolver will use (§7.2).
    is_binding = question.is_binding and (question.project_id in user.committees)

    # A binding -1 on unanimous_approval needs a non-empty comment (§8.3.1).
    if (
        question.approval_type == "unanimous_approval"
        and submitted.kind == "vote"
        and submitted.value == "-1"
        and is_binding
        and not (submitted.comment or "").strip()
    ):
        return jsonify({"error": "missing_veto_comment"}), 400

    # is_veto snapshot (§9.7).
    is_veto = (
        question.approval_type == "unanimous_approval"
        and submitted.kind == "vote"
        and submitted.value == "-1"
        and is_binding
        and bool((submitted.comment or "").strip())
    )

    # Acceptance ordering (§7.4): deadline absolutely wins ties.
    now = datetime.now(UTC)
    if now >= question.closes_at:
        return (
            jsonify(
                {
                    "error": "deadline_passed",
                    "closes_at": question.closes_at.isoformat(),
                }
            ),
            409,
        )
    if row["status"] != "open":
        return jsonify({"error": "not_open", "status": row["status"]}), 409

    response_id = str(uuid.uuid4())
    comment = getattr(submitted, "comment", None) if submitted.kind != "free_text" else None

    async with db.write_lock:
        try:
            db.conn.execute("BEGIN IMMEDIATE")
            dao.insert_response(
                db.conn,
                response_id=response_id,
                question_id=question_id,
                voter=user.uid,
                response_kind=submitted.kind,
                response_payload=submitted.model_dump(),
                comment=comment,
                is_binding=is_binding,
                is_veto=is_veto,
            )
            audit.record(
                db.conn,
                action="question.respond",
                actor=user.uid,
                question_id=question_id,
                response_id=response_id,
                details={
                    "response_kind": submitted.kind,
                    "is_binding": is_binding,
                    "is_veto": is_veto,
                },
            )
            db.conn.execute("COMMIT")
        except Exception:
            db.conn.execute("ROLLBACK")
            raise

    new_row = dao.fetch_response_row(db.conn, response_id)
    assert new_row is not None
    stored = dao.row_to_stored_response(new_row)

    _notify(
        "response",
        question,
        actor=user.uid,
        body=_summarize_response(
            submitted,
            voter=user.uid,
            is_binding=is_binding,
            is_veto=is_veto,
        ),
    )
    return stored, 201, {"Location": f"/question/{question_id}/responses/{response_id}"}


# Re-export the AuthenticatedUser symbol so other modules importing from this
# blueprint can still see it. Keeps the import surface stable for tests.
__all__ = ["questions_bp", "AuthenticatedUser"]
