"""Authentication helper tests."""

from __future__ import annotations

from types import SimpleNamespace

from cap_backend.auth import (
    AuthenticatedUser,
    _wants_json,
    can_view_question,
    is_public_path,
)


def _q(*, is_private: bool, project_id: str = "seapony"):
    return SimpleNamespace(is_private=is_private, project_id=project_id)


def test_public_paths_match_exactly():
    assert is_public_path("/api/api")
    assert is_public_path("/api/docs")
    assert is_public_path("/api/auth")
    assert is_public_path("/api/auth/login")
    # Resolution permalinks are public-readable (ACL-gated at the handler).
    assert is_public_path("/api/resolution/4217")
    assert not is_public_path("/api")
    assert not is_public_path("/api/list")
    assert not is_public_path("/auth")
    assert not is_public_path("/docs")
    assert not is_public_path("/")


def test_wants_json_default_is_json():
    assert _wants_json(None) is True
    assert _wants_json("") is True


def test_wants_json_prefers_json_over_html():
    assert _wants_json("application/json") is True
    assert _wants_json("text/html") is False
    assert _wants_json("text/html, application/json") is True  # JSON wins by presence


def test_can_view_public_question_always_true():
    user = AuthenticatedUser(uid="alice", committees=(), is_root=False)
    assert can_view_question(user, _q(is_private=False)) is True


def test_can_view_private_question_requires_membership_or_root():
    outsider = AuthenticatedUser(uid="alice", committees=("other",), is_root=False)
    assert can_view_question(outsider, _q(is_private=True)) is False

    member = AuthenticatedUser(uid="alice", committees=("seapony",), is_root=False)
    assert can_view_question(member, _q(is_private=True)) is True

    root = AuthenticatedUser(uid="alice", committees=(), is_root=True)
    assert can_view_question(root, _q(is_private=True)) is True


def test_can_view_private_question_grants_tooling_committee():
    tooling = AuthenticatedUser(uid="alice", committees=("tooling",), is_root=False)
    assert can_view_question(tooling, _q(is_private=True)) is True


def test_authenticated_user_from_session():
    session = SimpleNamespace(
        uid="bob",
        committees=["foo", "bar"],
        isRoot=False,
        fullname="Bob Bobson",
    )
    user = AuthenticatedUser.from_session(session)
    assert user.uid == "bob"
    assert user.committees == ("foo", "bar")
    assert user.is_root is False
    assert user.fullname == "Bob Bobson"
