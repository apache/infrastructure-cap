"""Pytest fixtures for the CAP backend test suite."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

import cap_backend.auth as auth_module
import cap_backend.notify as notify_module
from cap_backend.app import build_app
from cap_backend.auth import AuthenticatedUser
from cap_backend.config import DatabaseSettings, Settings


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@pytest.fixture
def tmp_db_path() -> Iterator[str]:
    with tempfile.TemporaryDirectory() as td:
        yield os.path.join(td, "cap.sqlite3")


@pytest.fixture
def settings(tmp_db_path: str) -> Settings:
    return Settings(database=DatabaseSettings(path=tmp_db_path))


@pytest_asyncio.fixture
async def app(settings: Settings) -> AsyncIterator:
    application = build_app(settings)
    async with application.test_app() as ctx:
        yield ctx.app


@pytest.fixture
def fake_user() -> AuthenticatedUser:
    return AuthenticatedUser(uid="alice", committees=("seapony",), is_root=False)


class _StubSession:
    def __init__(self, user: AuthenticatedUser):
        self.uid = user.uid
        self.committees = list(user.committees)
        self.isRoot = user.is_root
        self.fullname = user.fullname


@pytest.fixture
def stub_session(monkeypatch, fake_user: AuthenticatedUser):
    """Patch ``auth._read_session`` to return a stub matching ``fake_user``.

    Tests that want an unauthenticated request should not request this fixture.
    """

    state: dict[str, AuthenticatedUser] = {"user": fake_user}

    async def _read():
        return _StubSession(state["user"])

    monkeypatch.setattr(auth_module, "_read_session", _read)
    return state["user"]


@pytest.fixture
def as_user(monkeypatch):
    """Return a helper that swaps in a specific AuthenticatedUser at runtime."""

    state: dict[str, AuthenticatedUser | None] = {"user": None}

    async def _read():
        u = state["user"]
        return _StubSession(u) if u is not None else None

    monkeypatch.setattr(auth_module, "_read_session", _read)

    def _set(user: AuthenticatedUser | None) -> None:
        state["user"] = user

    return _set


@pytest.fixture
def captured_emails(monkeypatch) -> list[dict]:
    """Collect every call to ``notify._send_mail`` without contacting an MSA."""

    sent: list[dict] = []

    def _fake_send(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(notify_module, "_send_mail", _fake_send)
    return sent


@pytest.fixture
def seed_questions():
    """Return a helper that inserts question rows directly into the database."""
    import uuid

    def _insert(app, *, count: int = 1, **overrides) -> list[int]:
        db = app.extensions["cap_db"]
        now = datetime.now(UTC)
        ids: list[int] = []
        for i in range(count):
            defaults = {
                # Unique per row; the UNIQUE constraint on questions.request_id
                # (SPEC §7.1) means duplicate values would otherwise crash the
                # second seed_questions call in a test.
                "request_id": f"req_{uuid.uuid4().hex}",
                "project_id": "seapony",
                "title": f"Question {i}",
                "description": "...",
                "requester": "carol",
                "target_audience": "PMC: Apache SeaPony",
                "approval_type": "majority_approval",
                "response_option_json": json.dumps(
                    {
                        "kind": "vote",
                        "allowed_values": ["+1", "+0", "-0", "-1"],
                        "allow_comment": True,
                    }
                ),
                "is_binding": 1,
                "is_private": 0,
                "permalink": None,
                "status": "open",
                "outcome": None,
                "closes_at": _iso(now + timedelta(days=3)),
                "created_at": _iso(now),
                "updated_at": _iso(now),
            }
            defaults.update(overrides)
            cur = db.conn.execute(
                """
                INSERT INTO questions (
                    request_id, project_id, title, description, requester,
                    target_audience, approval_type, response_option_json,
                    is_binding, is_private, permalink, status, outcome,
                    closes_at, created_at, updated_at
                ) VALUES (
                    :request_id, :project_id, :title, :description, :requester,
                    :target_audience, :approval_type, :response_option_json,
                    :is_binding, :is_private, :permalink, :status, :outcome,
                    :closes_at, :created_at, :updated_at
                )
                """,
                defaults,
            )
            ids.append(cur.lastrowid)
        return ids

    return _insert


@pytest.fixture
def seed_response():
    """Append a row to ``responses``. Returns the response_id."""
    import uuid

    def _insert(
        app,
        *,
        question_id: int,
        voter: str,
        kind: str = "vote",
        value: str = "+1",
        comment: str | None = None,
        is_binding: bool = True,
        is_veto: bool = False,
        objection: bool = False,
        text: str | None = None,
        created_at: datetime | None = None,
    ) -> str:
        db = app.extensions["cap_db"]
        rid = str(uuid.uuid4())
        ts = _iso(created_at or datetime.now(UTC))
        if kind == "vote":
            payload = {"kind": "vote", "value": value, "comment": comment}
        elif kind == "lazy_consensus":
            payload = {"kind": "lazy_consensus", "objection": objection, "comment": comment}
        elif kind == "free_text":
            payload = {"kind": "free_text", "text": text or ""}
        else:
            raise ValueError(f"unknown kind {kind!r}")

        db.conn.execute(
            """
            INSERT INTO responses (
                response_id, question_id, voter, response_kind, response_json,
                comment, is_binding, is_veto, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                question_id,
                voter,
                kind,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                comment,
                1 if is_binding else 0,
                1 if is_veto else 0,
                ts,
                ts,
            ),
        )
        return rid

    return _insert
