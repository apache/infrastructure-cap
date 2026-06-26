"""Bearer-token endpoints. See SPEC §9.12."""

from __future__ import annotations

from typing import Any

from quart import Blueprint, current_app, jsonify
from quart_schema import document_response, validate_response

from cap_backend.auth import ROLE_ISSUE_SCOPE, current_user
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
    """Issue a new bearer token for the current user.

    Two callers may issue a token (SPEC §6.4, §9.12):

    * A fully-authenticated **OAuth session** mints a committee-limited
      personal access token (scoped to ``ask``).
    * A permanent **role-account credential** (a bearer token whose digest
      is configured under ``roleaccounts``) mints a cross-committee
      role-account token, also scoped to ``ask``. The minted token may
      create or resolve a question for any project, but is otherwise inert.

    Any *other* token session is refused: an ordinary PAT (or an already
    minted role-account token) cannot bootstrap further tokens. Either way
    the new token expires 24 hours after issuance, and no more than five
    tokens are kept live per uid.
    """
    user = await current_user()
    if user is None:
        return await _unauthenticated_response()

    # A permanent role-account credential carries the dedicated issue scope;
    # that is the one token session permitted to mint a token.
    is_role_issuer = user.scopes is not None and ROLE_ISSUE_SCOPE in user.scopes
    if user.is_token_session and not is_role_issuer:
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
    if is_role_issuer:
        # Cross-committee role-account token: no committee list is needed
        # because create/resolve waive the membership check for it.
        info = store.issue(
            uid=user.uid,
            committees=(),
            is_root=False,
            fullname=user.fullname,
            role_account=True,
        )
    else:
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
