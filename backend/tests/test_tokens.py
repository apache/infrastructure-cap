"""Personal-access-token store and /api/token endpoint tests. SPEC §6.4 + §9.12."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import cap_backend.auth as auth_module
from cap_backend.auth import AuthenticatedUser, user_has_scope
from cap_backend.tokens import (
    MAX_TOKENS_PER_UID,
    TOKEN_SCOPES,
    TOKEN_TTL,
    TokenStore,
    build_token_handler,
)


def test_issue_returns_distinct_tokens():
    store = TokenStore()
    a = store.issue(uid="alice", committees=("seapony",), is_root=False, fullname=None)
    b = store.issue(uid="alice", committees=("seapony",), is_root=False, fullname=None)
    assert a.token != b.token
    assert a.uid == "alice"
    assert a.scopes == TOKEN_SCOPES
    assert a.expires_at - a.created_at == TOKEN_TTL


def test_issue_evicts_oldest_when_uid_holds_five():
    store = TokenStore()
    issued = [
        store.issue(uid="alice", committees=("seapony",), is_root=False, fullname=None)
        for _ in range(MAX_TOKENS_PER_UID)
    ]
    # All five live tokens look up successfully.
    for info in issued:
        assert store.lookup(info.token) is not None

    sixth = store.issue(uid="alice", committees=("seapony",), is_root=False, fullname=None)
    # The oldest is now gone; the other four plus the sixth survive.
    assert store.lookup(issued[0].token) is None
    for info in issued[1:]:
        assert store.lookup(info.token) is not None
    assert store.lookup(sixth.token) is not None
    assert len(store.list_for_uid("alice")) == MAX_TOKENS_PER_UID


def test_lookup_purges_expired_tokens():
    store = TokenStore()
    info = store.issue(uid="alice", committees=("seapony",), is_root=False, fullname=None)
    # Force an expiry by rewriting the stored record's timestamps.
    expired = info.__class__(
        token=info.token,
        uid=info.uid,
        committees=info.committees,
        is_root=info.is_root,
        fullname=info.fullname,
        scopes=info.scopes,
        created_at=info.created_at - timedelta(hours=48),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    store._by_token[info.token] = expired
    assert store.lookup(info.token) is None
    assert store.list_for_uid("alice") == []


async def test_token_handler_returns_session_dict():
    store = TokenStore()
    info = store.issue(
        uid="alice", committees=("seapony", "tooling"), is_root=False, fullname="Alice"
    )
    handler = build_token_handler(store)

    session = await handler(info.token)
    assert session is not None
    assert session["uid"] == "alice"
    assert session["committees"] == ["seapony", "tooling"]
    assert session["metadata"]["scope"] == list(TOKEN_SCOPES)
    assert session["roleaccount"] is False

    assert (await handler("unknown-token")) is None


def test_authenticated_user_from_token_session_isolates_scope():
    """A session dict carrying metadata.scope must surface as a token session."""

    class _Sess:
        uid = "alice"
        committees = ["seapony"]
        isRoot = False
        fullname = None
        metadata = {"scope": ["ask"]}
        roleaccount = False

    user = AuthenticatedUser.from_session(_Sess())
    assert user.scopes == frozenset({"ask"})
    assert user.is_token_session is True
    assert user_has_scope(user, "ask") is True
    assert user_has_scope(user, "answer") is False
    # Public scope is granted to every authenticated caller, including tokens.
    assert user_has_scope(user, "public") is True


def test_authenticated_user_oauth_session_has_no_scope_restriction():
    """An OAuth session (no metadata.scope) must hold every scope implicitly."""

    class _Sess:
        uid = "alice"
        committees = ["seapony"]
        isRoot = False
        fullname = None
        # no `metadata` attribute at all → OAuth session
        roleaccount = False

    user = AuthenticatedUser.from_session(_Sess())
    assert user.scopes is None
    assert user.is_token_session is False
    for scope in ("public", "ask", "answer", "anything"):
        assert user_has_scope(user, scope) is True


# ---------------------------------------------------------------------------
# /api/token HTTP endpoint
# ---------------------------------------------------------------------------


async def test_post_token_issues_token_for_oauth_session(app, stub_session):
    client = app.test_client()
    response = await client.get("/api/token")
    assert response.status_code == 201
    body = await response.get_json()
    assert body["uid"] == "alice"
    assert body["scopes"] == ["ask"]
    assert isinstance(body["token"], str) and len(body["token"]) >= 32
    # Now look the token up in the in-memory store and confirm it was registered.
    store = app.extensions["cap_tokens"]
    assert store.lookup(body["token"]) is not None


async def test_post_token_unauthenticated_returns_401(app):
    client = app.test_client()
    response = await client.get("/api/token")
    assert response.status_code == 401


async def test_post_token_rejects_token_session(app, monkeypatch):
    """Tokens cannot bootstrap further tokens (SPEC §9.12)."""

    class _TokenSession:
        uid = "alice"
        committees = ["seapony"]
        isRoot = False
        fullname = None
        metadata = {"scope": ["ask"]}
        roleaccount = False

    async def _read():
        return _TokenSession()

    monkeypatch.setattr(auth_module, "_read_session", _read)
    client = app.test_client()
    response = await client.get("/api/token")
    assert response.status_code == 403
    body = await response.get_json()
    assert body["error"] == "token_session_cannot_issue"


async def test_post_token_respects_per_uid_cap(app, stub_session):
    client = app.test_client()
    tokens: list[str] = []
    for _ in range(MAX_TOKENS_PER_UID + 2):
        response = await client.get("/api/token")
        assert response.status_code == 201
        body = await response.get_json()
        tokens.append(body["token"])

    store = app.extensions["cap_tokens"]
    assert len(store.list_for_uid("alice")) == MAX_TOKENS_PER_UID
    # First two are evicted, last five remain.
    assert store.lookup(tokens[0]) is None
    assert store.lookup(tokens[1]) is None
    for tok in tokens[2:]:
        assert store.lookup(tok) is not None


# ---------------------------------------------------------------------------
# Scope enforcement on the existing API endpoints
# ---------------------------------------------------------------------------


class _TokenSessionUser:
    def __init__(self, scopes: list[str], committees: list[str] = ("seapony",)):
        self.uid = "alice"
        self.committees = list(committees)
        self.isRoot = False
        self.fullname = "Alice"
        self.metadata = {"scope": list(scopes)}
        self.roleaccount = False


@pytest.fixture
def token_session(monkeypatch):
    """Helper: monkeypatch ``_read_session`` to return a token-style session."""

    state: dict[str, _TokenSessionUser | None] = {"session": None}

    async def _read():
        return state["session"]

    monkeypatch.setattr(auth_module, "_read_session", _read)

    def _set(scopes: list[str], **kw) -> None:
        state["session"] = _TokenSessionUser(scopes=scopes, **kw)

    return _set


async def test_ask_token_can_create_question(app, token_session):
    token_session(scopes=["ask"])
    client = app.test_client()
    body = {
        "project_id": "seapony",
        "title": "Ask-scoped question",
        "description": "via token",
        "target_audience": "PMC: Apache SeaPony",
        "approval_type": "majority_approval",
        "is_binding": True,
        "is_private": False,
        "response_option": {
            "kind": "vote",
            "allowed_values": ["+1", "+0", "-0", "-1"],
            "allow_comment": True,
        },
        "closes_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
    }
    response = await client.post("/api/question", json=body)
    assert response.status_code == 201


async def test_ask_token_cannot_answer(app, token_session, seed_questions):
    token_session(scopes=["ask"])
    qids = seed_questions(app, count=1)
    client = app.test_client()
    response = await client.post(
        f"/api/question/{qids[0]}/responses",
        json={"kind": "vote", "value": "+1"},
    )
    assert response.status_code == 403
    body = await response.get_json()
    assert body["error"] == "insufficient_scope"
    assert body["required_scope"] == "answer"


async def test_ask_token_can_call_public_scope_endpoints(app, token_session, seed_questions):
    """Public-scope endpoints are open to every authenticated caller, tokens included."""
    token_session(scopes=["ask"])
    seed_questions(app, count=1)
    client = app.test_client()
    response = await client.get("/api/list")
    assert response.status_code == 200


async def test_answer_only_token_cannot_create_question(app, token_session):
    token_session(scopes=["answer"])
    client = app.test_client()
    body = {
        "project_id": "seapony",
        "title": "No-ask",
        "description": "...",
        "target_audience": "PMC: Apache SeaPony",
        "approval_type": "majority_approval",
        "is_binding": True,
        "is_private": False,
        "response_option": {
            "kind": "vote",
            "allowed_values": ["+1", "+0", "-0", "-1"],
            "allow_comment": True,
        },
        "closes_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
    }
    response = await client.post("/api/question", json=body)
    assert response.status_code == 403
    body = await response.get_json()
    assert body["error"] == "insufficient_scope"
    assert body["required_scope"] == "ask"
