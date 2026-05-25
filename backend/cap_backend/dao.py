"""SQLite data-access helpers for the ``questions`` and ``responses`` tables.

The module is intentionally a thin wrapper around plain ``sqlite3`` calls.
The caller owns the transaction (so the audit-log insert and the table
write can happen atomically); these functions execute their statements
against a connection and return the parsed result, but never commit.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from cap_backend.auth import AuthenticatedUser
from cap_backend.schemas.questions import Question, StoredResponse


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def row_to_question(
    row: sqlite3.Row,
    *,
    viewer: AuthenticatedUser,
    now: datetime | None = None,
) -> Question:
    """Project a ``questions`` row into the public ``Question`` model.

    ``viewer_is_binding`` and ``time_remaining_seconds`` are server-computed
    per request (SPEC §8.3), so this helper requires the requesting user.
    """
    closes_at = _parse_iso(row["closes_at"])
    created_at = _parse_iso(row["created_at"])
    if now is None:
        now = datetime.now(UTC)

    response_option: Any = json.loads(row["response_option_json"])
    viewer_is_binding = bool(row["is_binding"]) and (row["project_id"] in viewer.committees)
    remaining = int((closes_at - now).total_seconds())

    return Question.model_validate(
        {
            "question_id": row["question_id"],
            "request_id": row["request_id"],
            "project_id": row["project_id"],
            "title": row["title"],
            "description": row["description"],
            "requester": row["requester"],
            "target_audience": row["target_audience"],
            "approval_type": row["approval_type"],
            "is_binding": bool(row["is_binding"]),
            "is_private": bool(row["is_private"]),
            "response_option": response_option,
            "permalink": row["permalink"],
            "status": row["status"],
            "outcome": row["outcome"],
            "created_at": created_at,
            "closes_at": closes_at,
            "viewer_is_binding": viewer_is_binding,
            "time_remaining_seconds": max(0, remaining),
        }
    )


def row_to_stored_response(row: sqlite3.Row) -> StoredResponse:
    return StoredResponse.model_validate(
        {
            "response_id": row["response_id"],
            "question_id": row["question_id"],
            "voter": row["voter"],
            "response_kind": row["response_kind"],
            "response": json.loads(row["response_json"]),
            "comment": row["comment"],
            "is_binding": bool(row["is_binding"]),
            "is_veto": bool(row["is_veto"]),
            "created_at": _parse_iso(row["created_at"]),
        }
    )


def fetch_question_row(conn: sqlite3.Connection, question_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT question_id, request_id, project_id, title, description, requester,
               target_audience, approval_type, response_option_json, is_binding,
               is_private, permalink, status, outcome, closes_at, created_at, updated_at
          FROM questions
         WHERE question_id = ?
        """,
        (question_id,),
    ).fetchone()


def insert_question(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    project_id: str,
    title: str,
    description: str,
    requester: str,
    target_audience: str,
    approval_type: str,
    response_option: dict[str, Any],
    is_binding: bool,
    is_private: bool,
    closes_at: datetime,
) -> int:
    now = _now_iso()
    cursor = conn.execute(
        """
        INSERT INTO questions (
            request_id, project_id, title, description, requester,
            target_audience, approval_type, response_option_json,
            is_binding, is_private, permalink, status, outcome,
            closes_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'open', NULL, ?, ?, ?)
        """,
        (
            request_id,
            project_id,
            title,
            description,
            requester,
            target_audience,
            approval_type,
            json.dumps(response_option, separators=(",", ":"), sort_keys=True),
            1 if is_binding else 0,
            1 if is_private else 0,
            closes_at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            now,
            now,
        ),
    )
    question_id = cursor.lastrowid
    if question_id is None:
        raise RuntimeError("INSERT did not return a question_id")
    return question_id


_EDITABLE_FIELDS = ("title", "description", "target_audience", "closes_at", "is_private")


def apply_edits(
    conn: sqlite3.Connection,
    *,
    question_id: int,
    current_row: sqlite3.Row,
    edits: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Apply ``edits`` to ``question_id`` and return the diff for the audit log.

    ``edits`` may carry any of the editable fields plus ``response_option``.
    Only fields whose value actually changes are written and surfaced in the
    returned diff. Returns an empty dict if nothing changed.
    """
    diff: dict[str, dict[str, Any]] = {}
    updates: dict[str, Any] = {}

    for field in _EDITABLE_FIELDS:
        if field not in edits:
            continue
        new_value = edits[field]
        if field == "closes_at" and isinstance(new_value, datetime):
            new_value = (
                new_value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
            )
        elif field == "is_private":
            new_value = 1 if new_value else 0

        old_value = current_row[field]
        if old_value != new_value:
            diff[field] = {"before": old_value, "after": new_value}
            updates[field] = new_value

    if "response_option" in edits and edits["response_option"] is not None:
        new_option_json = json.dumps(
            edits["response_option"], separators=(",", ":"), sort_keys=True
        )
        if current_row["response_option_json"] != new_option_json:
            diff["response_option"] = {
                "before": json.loads(current_row["response_option_json"]),
                "after": edits["response_option"],
            }
            updates["response_option_json"] = new_option_json

    if not updates:
        return diff

    set_clause = ", ".join(f"{name} = :{name}" for name in updates)
    params = dict(updates)
    params["updated_at"] = _now_iso()
    params["question_id"] = question_id
    conn.execute(
        f"UPDATE questions SET {set_clause}, updated_at = :updated_at WHERE question_id = :question_id",
        params,
    )
    return diff


def mark_removed(conn: sqlite3.Connection, question_id: int) -> None:
    conn.execute(
        """
        UPDATE questions
           SET status = 'removed', outcome = 'withdrawn', updated_at = ?
         WHERE question_id = ?
        """,
        (_now_iso(), question_id),
    )


def mark_resolved(
    conn: sqlite3.Connection,
    *,
    question_id: int,
    outcome: str,
    permalink: str,
) -> None:
    conn.execute(
        """
        UPDATE questions
           SET status = 'resolved', outcome = ?, permalink = ?, updated_at = ?
         WHERE question_id = ?
        """,
        (outcome, permalink, _now_iso(), question_id),
    )


def insert_response(
    conn: sqlite3.Connection,
    *,
    response_id: str,
    question_id: int,
    voter: str,
    response_kind: str,
    response_payload: dict[str, Any],
    comment: str | None,
    is_binding: bool,
    is_veto: bool,
) -> None:
    """Append one row to ``responses``.

    A voter amending an earlier response writes a *new* row; existing rows
    are never updated. See SPEC §7.2 ("latest per (question_id, voter) wins").
    """
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO responses (
            response_id, question_id, voter, response_kind, response_json,
            comment, is_binding, is_veto, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            response_id,
            question_id,
            voter,
            response_kind,
            json.dumps(response_payload, separators=(",", ":"), sort_keys=True),
            comment,
            1 if is_binding else 0,
            1 if is_veto else 0,
            now,
            now,
        ),
    )


def fetch_response_row(conn: sqlite3.Connection, response_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT response_id, question_id, voter, response_kind, response_json,
               comment, is_binding, is_veto, created_at, updated_at
          FROM responses
         WHERE response_id = ?
        """,
        (response_id,),
    ).fetchone()


def fetch_all_response_rows(conn: sqlite3.Connection, question_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT response_id, question_id, voter, response_kind, response_json,
               comment, is_binding, is_veto, created_at, updated_at
          FROM responses
         WHERE question_id = ?
         ORDER BY created_at ASC, response_id ASC
        """,
        (question_id,),
    ).fetchall()


def latest_response_per_voter(rows: list[sqlite3.Row]) -> dict[str, sqlite3.Row]:
    """Return ``{voter: latest_row}`` from rows ordered ascending by time."""
    latest: dict[str, sqlite3.Row] = {}
    for row in rows:
        latest[row["voter"]] = row
    return latest
