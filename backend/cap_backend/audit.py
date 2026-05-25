"""Audit-log helpers. See SPEC section 7.3.

The audit log is append-only and is the source of truth for the pubsub
publisher. Callers MUST invoke ``record`` inside the same SQLite transaction
that performed the state-changing write.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, Literal

AuditAction = Literal[
    "question.create",
    "question.edit",
    "question.respond",
    "question.resolve",
    "question.remove",
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def record(
    conn: sqlite3.Connection,
    *,
    action: AuditAction,
    actor: str,
    question_id: int | None = None,
    response_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> int:
    """Insert a single row into ``audit_log`` and return its ``audit_id``.

    The caller owns the surrounding transaction; this function does not commit.
    """
    cursor = conn.execute(
        """
        INSERT INTO audit_log (occurred_at, actor, action, question_id, response_id, details_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            _now_iso(),
            actor,
            action,
            question_id,
            response_id,
            json.dumps(details or {}, separators=(",", ":"), sort_keys=True),
        ),
    )
    audit_id = cursor.lastrowid
    if audit_id is None:
        raise RuntimeError("audit_log insert did not return a row id")
    return audit_id
