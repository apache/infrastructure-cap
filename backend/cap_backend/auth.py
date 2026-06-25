"""Authentication helpers. See SPEC section 6 and 7.5."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from quart import jsonify, redirect, request

if TYPE_CHECKING:
    from cap_backend.schemas.questions import Question

# The unauthenticated paths in the service. /api/auth is the ASF OAuth
# gateway (it has to be reachable without a session, to perform the login
# handshake); /api/api is the public OpenAPI document; /api/docs is the
# Swagger UI page that renders it; /api/publist is the public read-only
# feed of non-private questions (SPEC §9.13). SPEC section 6, point 1.
#
# /api/question and /api/resolution are exempt from the *global* hook but
# remain ACL-gated at the handler: read handlers treat an unauthenticated
# caller as a viewer with no committees, so public rows are returned and
# private rows collapse to 404 (SPEC §7.5, §9.3, §9.8); state-changing
# handlers under /api/question re-check authentication themselves and
# return their own 401.
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/api/api",
        "/api/docs",
        "/api/publist",
        "/api/question",
        "/api/resolution",
    }
)
OAUTH_PATH_PREFIX = "/api/auth"


@dataclass(frozen=True)
class AuthenticatedUser:
    """Slim projection of the asfquart session carried by request handlers."""

    uid: str
    committees: tuple[str, ...] = ()
    is_root: bool = False
    fullname: str | None = None
    # ``scopes`` is ``None`` for full OAuth sessions (which carry every
    # scope implicitly) and a frozenset of scope names for bearer-token
    # sessions (which are limited to the scopes declared at issuance).
    # See SPEC §6.3 / §6.4.
    scopes: frozenset[str] | None = None
    is_token_session: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_session(cls, session: Any) -> AuthenticatedUser:
        committees = tuple(getattr(session, "committees", None) or [])
        metadata = getattr(session, "metadata", None)
        scope_list: list[str] | None = None
        if isinstance(metadata, dict):
            raw_scope = metadata.get("scope")
            if isinstance(raw_scope, (list, tuple, set, frozenset)):
                scope_list = [str(s) for s in raw_scope]
        scopes = frozenset(scope_list) if scope_list is not None else None
        is_token_session = scopes is not None or bool(getattr(session, "roleaccount", False))
        return cls(
            uid=session.uid,
            committees=committees,
            is_root=bool(getattr(session, "isRoot", False)),
            fullname=getattr(session, "fullname", None),
            scopes=scopes,
            is_token_session=is_token_session,
        )


def is_public_path(path: str) -> bool:
    """Return True for paths exempt from the global authentication hook."""
    for _path in PUBLIC_PATHS:
        if path.startswith(_path):
            return True
    return path == OAUTH_PATH_PREFIX or path.startswith(OAUTH_PATH_PREFIX + "/")


def _wants_json(accept_header: str | None) -> bool:
    """Decide whether the caller prefers a JSON 401 over an HTML redirect.

    Browser-style requests (Accept includes text/html) get redirected to the
    OAuth gateway; API-style requests (Accept includes application/json) get
    a 401 with a JSON body. Anything ambiguous falls back to JSON, which is
    the safe default for an API server.
    """
    if not accept_header:
        return True
    lowered = accept_header.lower()
    if "application/json" in lowered:
        return True
    if "text/html" in lowered:
        return False
    return True


def _login_url(target_path: str) -> str:
    query = urlencode({"login": target_path})
    return f"{OAUTH_PATH_PREFIX}?{query}"


async def _read_session() -> Any:
    """Read the current asfquart session, if any. Imports lazily to keep the
    module testable without a running asfquart app."""
    from asfquart import session as asfquart_session  # noqa: PLC0415

    return await asfquart_session.read()


async def require_authentication():
    """``before_request`` hook enforcing global authentication.

    Returns ``None`` for authenticated or public requests (which lets Quart
    proceed to the matched route handler); returns a Response otherwise.
    """
    path = request.path or "/"
    if is_public_path(path):
        return None

    session = await _read_session()
    if session is not None and getattr(session, "uid", None):
        return None

    accept = request.headers.get("Accept")
    login_url = _login_url(request.full_path or path)
    if _wants_json(accept):
        body = jsonify(
            {
                "error": "authentication_required",
                "login_url": login_url,
            }
        )
        return body, 401
    return redirect(login_url)


async def current_user() -> AuthenticatedUser | None:
    """Return the current authenticated user, or None.

    Routes that have passed through the global hook can assume this returns a
    non-None value; the helper still returns Optional so it remains usable
    from places that may run before the hook (tests, background tasks).
    """
    session = await _read_session()
    if session is None or not getattr(session, "uid", None):
        return None
    return AuthenticatedUser.from_session(session)


# Scope names known to the API. ``public`` is the implicit catch-all that
# any authenticated caller may use; ``ask`` and ``answer`` correspond to
# the question-management and response-submission endpoint groups
# (SPEC §6.3).
PUBLIC_SCOPE = "public"
ASK_SCOPE = "ask"
ANSWER_SCOPE = "answer"


def user_has_scope(user: AuthenticatedUser, scope: str) -> bool:
    """Return True if ``user`` is allowed to call an endpoint requiring ``scope``.

    OAuth sessions (``user.scopes is None``) always pass. Bearer-token
    sessions pass iff ``scope`` is ``public`` (every authenticated caller
    has implicit public-scope access) or the scope appears in their
    issued scope list.
    """
    if not user or user.scopes is None:
        return True
    if scope == PUBLIC_SCOPE:
        return True
    return scope in user.scopes


def can_view_question(user: AuthenticatedUser, question: Question | Any) -> bool:
    """Implements the private-question ACL from SPEC section 7.5.

    Accepts either a Question Pydantic model or any object exposing
    ``is_private`` and ``project_id`` attributes (so the helper can be used
    with raw rows during list queries too).
    """
    is_private = bool(getattr(question, "is_private", False))
    if not is_private:
        return True
    if user.is_root:
        return True
    project_id = getattr(question, "project_id", None)
    if project_id and project_id in user.committees:
        return True
    if "tooling" in user.committees:
        return True
    return False
