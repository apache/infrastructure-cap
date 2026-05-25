"""Pubsub publisher. See SPEC §10.

State-changing actions are tailed from the ``audit_log`` table and republished
as JSON dictionaries to a `pypubsub`_ instance, so downstream subscribers
(auditors, dashboards, project tooling) can react in near-real-time without
polling the API.

This module is the **only** sanctioned place that converts internal records
into outbound JSON. It works exclusively from rows already persisted in
SQLite, which by construction do not contain client IP addresses, request
headers, OAuth tokens, or any other request-time PII (SPEC §10.3).

.. _pypubsub: https://github.com/humbedooh/pypubsub
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

from cap_backend import dao
from cap_backend.auth import AuthenticatedUser
from cap_backend.config import Settings

LOGGER = logging.getLogger(__name__)

# Maps ``audit_log.action`` -> the URL "type" segment from SPEC §10.1.
_ACTION_TO_TYPE: dict[str, str] = {
    "question.create": "created",
    "question.edit": "edited",
    "question.respond": "response",
    "question.resolve": "resolved",
    "question.remove": "closed",
}

# Sentinel "viewer" used when serializing a Question into a pubsub payload.
# Pubsub consumers are not viewer-specific, so ``viewer_is_binding`` is
# always false in the published shape; ``time_remaining_seconds`` is
# computed against the publisher's clock at send time, which mirrors what
# ``/list`` does for live requests.
_PUBSUB_VIEWER = AuthenticatedUser(uid="_pubsub", committees=(), is_root=False)


# ---------------------------------------------------------------------------
# Cursor helpers (SPEC §10.4)
# ---------------------------------------------------------------------------


def read_cursor(conn: sqlite3.Connection) -> int:
    """Return the last ``audit_id`` that was successfully published, or 0."""
    row = conn.execute("SELECT last_audit_id FROM pubsub_cursor WHERE id = 1").fetchone()
    if row is None:
        # Schema bootstrap inserts the cursor row, but be defensive.
        conn.execute(
            "INSERT OR IGNORE INTO pubsub_cursor (id, last_audit_id) VALUES (1, 0)"
        )
        return 0
    return int(row["last_audit_id"])


def write_cursor(conn: sqlite3.Connection, audit_id: int) -> None:
    """Persist ``audit_id`` as the last successfully published row."""
    conn.execute(
        "UPDATE pubsub_cursor SET last_audit_id = ? WHERE id = 1",
        (audit_id,),
    )


def _fetch_audit_batch(
    conn: sqlite3.Connection, after_id: int, *, limit: int = 64
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT audit_id, occurred_at, actor, action, question_id, response_id, details_json
          FROM audit_log
         WHERE audit_id > ?
         ORDER BY audit_id ASC
         LIMIT ?
        """,
        (after_id, limit),
    ).fetchall()


# ---------------------------------------------------------------------------
# Payload assembly (SPEC §10.2)
# ---------------------------------------------------------------------------


def _serialize_question(
    conn: sqlite3.Connection, question_id: int
) -> dict[str, Any] | None:
    row = dao.fetch_question_row(conn, question_id)
    if row is None:
        return None
    return dao.row_to_question(row, viewer=_PUBSUB_VIEWER).model_dump(mode="json")


def build_event_payload(
    conn: sqlite3.Connection, audit_row: sqlite3.Row
) -> dict[str, Any] | None:
    """Return the JSON body for the pubsub event derived from ``audit_row``.

    Returns ``None`` when the row should be silently skipped (unknown action,
    no associated question, or the referenced question has been hard-deleted
    so we can no longer serialize it). The caller advances the cursor past
    skipped rows so the publisher never loops on an undeliverable entry.
    """
    action = audit_row["action"]
    event_type = _ACTION_TO_TYPE.get(action)
    if event_type is None:
        return None

    qid = audit_row["question_id"]
    if qid is None:
        return None

    question = _serialize_question(conn, qid)
    if question is None:
        return None

    details: dict[str, Any] = json.loads(audit_row["details_json"] or "{}")

    payload: dict[str, Any] = {
        "action": event_type,
        "question": question,
        "actor": audit_row["actor"],
        "occurred_at": audit_row["occurred_at"],
        "audit_id": audit_row["audit_id"],
    }

    if event_type == "response" and audit_row["response_id"]:
        response_row = dao.fetch_response_row(conn, audit_row["response_id"])
        if response_row is not None:
            payload["response"] = dao.row_to_stored_response(response_row).model_dump(
                mode="json"
            )
    elif event_type == "resolved":
        # The resolve handler already wrote both into details_json.
        payload["tally"] = details.get("tally")
        if "permalink" in details:
            payload["permalink"] = details["permalink"]
    elif event_type == "edited":
        if "diff" in details:
            payload["diff"] = details["diff"]

    return payload


# ---------------------------------------------------------------------------
# URL builder (SPEC §10.1)
# ---------------------------------------------------------------------------


def build_url(
    base_url: str, *, is_private: bool, event_type: str, project: str, question_id: int
) -> str:
    """Build the pypubsub topic URL for one event."""
    private_prefix = "/private" if is_private else ""
    return (
        f"{base_url.rstrip('/')}{private_prefix}/question/"
        f"{event_type}/{project}/{question_id}"
    )


def _basic_auth_header(username: str | None, password: str | None) -> dict[str, str]:
    if not username or not password:
        return {}
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# ---------------------------------------------------------------------------
# HTTP send (overridable for tests)
# ---------------------------------------------------------------------------


SendCallable = Callable[[str, dict[str, Any], dict[str, str], float], Awaitable[int]]


async def _default_send(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> int:
    """POST ``payload`` to ``url`` using aiohttp; return the HTTP status code.

    aiohttp is already in the dep tree via asfquart, so we avoid adding a new
    HTTP client. The function is the only place the publisher touches the
    network; tests monkeypatch ``PubsubPublisher._send`` directly so this
    coroutine is never reached in the test suite.
    """
    import aiohttp  # noqa: PLC0415 - lazy import keeps the module light

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            return resp.status


# ---------------------------------------------------------------------------
# Publisher coroutine
# ---------------------------------------------------------------------------


class PubsubPublisher:
    """Background task that tails ``audit_log`` and POSTs events to pypubsub.

    Started by ``cap_backend.app`` on application startup when
    ``settings.pubsub.enabled`` is true. The loop processes one batch of
    audit rows at a time, advances the cursor only after each individual
    row is successfully delivered (or determined to be unpublishable), and
    stops cleanly when ``stop()`` is awaited.
    """

    def __init__(
        self,
        db: Any,
        settings: Settings,
        *,
        poll_interval: float = 2.0,
        max_backoff: float = 60.0,
        send: SendCallable | None = None,
    ):
        self.db = db
        self.settings = settings
        self.poll_interval = poll_interval
        self.max_backoff = max_backoff
        self._send: SendCallable = send or _default_send
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._backoff = poll_interval

    # ---- lifecycle -------------------------------------------------------

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self._task is not None:
            return
        if not self.settings.pubsub.enabled:
            LOGGER.info("Pubsub publisher disabled by config; not starting.")
            return
        self._stop.clear()
        self._backoff = self.poll_interval
        self._task = asyncio.create_task(self._run(), name="cap-pubsub-publisher")
        LOGGER.info(
            "Pubsub publisher started: base_url=%s", self.settings.pubsub.base_url
        )

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            # Either cancellation or a leftover failure; either way the
            # background work is done. Swallow so shutdown is robust.
            pass
        finally:
            self._task = None

    # ---- main loop -------------------------------------------------------

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    progressed = await self._process_batch()
                except Exception as exc:  # noqa: BLE001 - never crash the loop
                    LOGGER.warning("Pubsub publisher iteration failed: %s", exc)
                    progressed = False
                if progressed:
                    # We made progress; reset backoff to the poll interval.
                    self._backoff = self.poll_interval
                    continue
                # No new events or transient failure; sleep with backoff.
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._backoff)
                    break  # stop event fired
                except TimeoutError:
                    pass
                if self._backoff < self.max_backoff:
                    self._backoff = min(self._backoff * 2, self.max_backoff)
        except asyncio.CancelledError:
            pass

    async def _process_batch(self) -> bool:
        """Process one batch of pending audit rows.

        Returns True when at least one row was handled (so the loop should
        keep going without sleeping); False when there is nothing to do or
        a transient failure forced an early exit (so the loop should back
        off and try again).
        """
        conn = self.db.conn
        after = read_cursor(conn)
        rows = _fetch_audit_batch(conn, after)
        if not rows:
            return False

        for row in rows:
            handled = await self._publish_one(row)
            if not handled:
                # Transient failure: leave the cursor alone so the same row
                # is retried on the next iteration.
                return False
            async with self.db.write_lock:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    write_cursor(conn, int(row["audit_id"]))
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        return True

    async def _publish_one(self, audit_row: sqlite3.Row) -> bool:
        """Publish exactly one audit row.

        Returns True when the row is considered processed (either delivered
        successfully or intentionally skipped per §10.4) so the caller can
        advance the cursor past it; False on transient failures so the
        caller leaves the cursor alone and retries later.
        """
        conn = self.db.conn
        payload = build_event_payload(conn, audit_row)
        if payload is None:
            LOGGER.debug(
                "Pubsub: nothing to publish for audit_id=%s (action=%s)",
                audit_row["audit_id"],
                audit_row["action"],
            )
            return True  # cursor advances past undeliverable entries

        question = payload["question"]
        is_private = bool(question.get("is_private"))
        project = str(question["project_id"])
        qid = int(question["question_id"])
        event_type = str(payload["action"])

        url = build_url(
            self.settings.pubsub.base_url,
            is_private=is_private,
            event_type=event_type,
            project=project,
            question_id=qid,
        )

        auth = self.settings.pubsub.basic_auth
        if is_private and (not auth.username or not auth.password):
            LOGGER.warning(
                "Pubsub: skipping private event %s for question %s "
                "(no basic_auth credentials configured)",
                event_type,
                qid,
            )
            return True  # cursor still advances (§10.4)

        headers = _basic_auth_header(auth.username, auth.password)
        try:
            status = await self._send(
                url, payload, headers, float(self.settings.pubsub.timeout_seconds)
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Pubsub POST to %s failed: %s", url, exc)
            return False

        if 200 <= status < 300:
            LOGGER.debug("Pubsub POST %s -> %s", url, status)
            return True
        LOGGER.warning("Pubsub POST %s returned non-2xx: %s", url, status)
        return False
