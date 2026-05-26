"""Bearer-token endpoints. See SPEC §9.12."""

from __future__ import annotations

from typing import Any

from quart import Blueprint, current_app, jsonify
from quart_schema import document_response, validate_response

from cap_backend.auth import current_user
from cap_backend.schemas.errors import AuthenticationRequired, ErrorMessage
from cap_backend.schemas.tokens import TokenIssued

tokens_bp = Blueprint("tokens", __name__)


async def _unauthenticated_response() -> tuple[Any, int]:
    return (
        jsonify({"error": "authentication_required", "login_url": "/api/auth"}),
        401,
    )


@tokens_bp.get("/token")
@validate_response(TokenIssued, 201)
@document_response(AuthenticationRequired, 401)
@document_response(ErrorMessage, 403)
async def issue_token() -> Any:
    """Issue a new personal-access bearer token for the current user.

    Tokens may only be issued from a fully-authenticated OAuth session
    (token-based sessions cannot bootstrap further tokens). The new
    token is scoped to ``ask`` only and expires 24 hours after issuance;
    no more than five tokens are kept live per user.
    """
    user = await current_user()
    if user is None:
        return await _unauthenticated_response()
    if user.is_token_session:
        return (
            jsonify(
                {
                    "error": "token_session_cannot_issue",
                    "detail": "Personal access tokens may only be issued from an OAuth session.",
                }
            ),
            403,
        )

    store = current_app.extensions["cap_tokens"]
    info = store.issue(
        uid=user.uid,
        committees=user.committees,
        is_root=user.is_root,
        fullname=user.fullname,
    )
    return (
        TokenIssued(
            token=info.token,
            uid=info.uid,
            scopes=list(info.scopes),
            created_at=info.created_at,
            expires_at=info.expires_at,
        ),
        201,
    )


__all__ = ["tokens_bp"]
