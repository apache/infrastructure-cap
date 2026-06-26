"""Personal-access-token (bearer) store. See SPEC section 6.4.

Tokens are held entirely in process memory: they do not survive a restart,
and they are not shared between worker processes. Each issued token is
bound to one ASF UID, scoped exclusively to ``ask``, and expires 24 hours
after issuance. At most five tokens may be live for a single uid; issuing
a sixth evicts the oldest.

Two kinds of tokens authenticate against this store:

* **Personal access tokens (PATs)** minted by an OAuth user. Committee-
  limited (they carry the issuer's committee list), ``roleaccount=False``.
* **Role-account tokens** minted from a configured permanent role-account
  credential (section 6.4). Cross-committee (no committee list is needed,
  the create/resolve handlers waive the membership check for them) and
  flagged ``role_account=True``. They otherwise behave exactly like PATs:
  same ``ask`` scope, same 24h TTL, same per-uid cap.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cap_backend.auth import ROLE_ISSUE_SCOPE

TOKEN_TTL: timedelta = timedelta(hours=24)
MAX_TOKENS_PER_UID: int = 5
TOKEN_SCOPES: tuple[str, ...] = ("ask",)


@dataclass(frozen=True)
class IssuedToken:
    """One live personal access token."""

    token: str
    uid: str
    committees: tuple[str, ...]
    is_root: bool
    fullname: str | None
    scopes: tuple[str, ...]
    created_at: datetime
    expires_at: datetime
    # True for tokens minted from a permanent role-account credential. The
    # create/resolve handlers waive the committee/requester ownership check
    # for these so a role account can act on behalf of any project.
    role_account: bool = False


@dataclass(frozen=True)
class RoleAccountCredential:
    """A permanent role-account credential resolved from config (§6.4)."""

    uid: str
    fullname: str | None = None


class TokenStore:
    """Thread-safe in-memory store of personal access tokens."""

    def __init__(self) -> None:
        self._by_token: dict[str, IssuedToken] = {}
        # Per-uid insertion-ordered list of live token strings, oldest first.
        # Used to enforce MAX_TOKENS_PER_UID by evicting from the front.
        self._by_uid: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def _purge_expired_locked(self, now: datetime) -> None:
        expired = [tok for tok, info in self._by_token.items() if info.expires_at <= now]
        for tok in expired:
            info = self._by_token.pop(tok)
            uid_tokens = self._by_uid.get(info.uid)
            if uid_tokens and tok in uid_tokens:
                uid_tokens.remove(tok)
                if not uid_tokens:
                    del self._by_uid[info.uid]

    def issue(
        self,
        *,
        uid: str,
        committees: tuple[str, ...],
        is_root: bool,
        fullname: str | None,
        role_account: bool = False,
    ) -> IssuedToken:
        """Issue a new token for ``uid``. Evicts the oldest if 5 are already live."""
        now = datetime.now(UTC)
        with self._lock:
            self._purge_expired_locked(now)
            uid_tokens = self._by_uid.setdefault(uid, [])
            while len(uid_tokens) >= MAX_TOKENS_PER_UID:
                oldest = uid_tokens.pop(0)
                self._by_token.pop(oldest, None)
            token_str = secrets.token_urlsafe(32)
            info = IssuedToken(
                token=token_str,
                uid=uid,
                committees=tuple(committees),
                is_root=is_root,
                fullname=fullname,
                scopes=TOKEN_SCOPES,
                created_at=now,
                expires_at=now + TOKEN_TTL,
                role_account=role_account,
            )
            self._by_token[token_str] = info
            uid_tokens.append(token_str)
            return info

    def lookup(self, token: str) -> IssuedToken | None:
        """Return the live token info for ``token``, or None if absent/expired."""
        now = datetime.now(UTC)
        with self._lock:
            self._purge_expired_locked(now)
            return self._by_token.get(token)

    def list_for_uid(self, uid: str) -> list[IssuedToken]:
        now = datetime.now(UTC)
        with self._lock:
            self._purge_expired_locked(now)
            return [self._by_token[t] for t in self._by_uid.get(uid, []) if t in self._by_token]


def build_token_handler(
    store: TokenStore,
    role_accounts: dict[str, RoleAccountCredential] | None = None,
):
    """Return an async function suitable for ``asfquart.APP.token_handler``.

    Per the asfquart sessions doc, the handler receives the raw bearer token
    and returns either ``None`` (unknown/expired) or a session-dict carrying
    the uid, committees, and ``metadata.scope`` list.

    ``role_accounts`` maps the SHA-256 hex digest of each permanent role-
    account token to its credential (section 6.4). A presented token is
    resolved in two steps:

    1. If it is a live token in the in-memory store, return that session
       (a PAT, or a previously minted temporary role-account token).
    2. Otherwise, if ``sha256(token)`` matches a configured role account,
       return the permanent credential's session. That session carries only
       the ``roleaccount`` issue scope, so it can mint a temporary token at
       ``GET /api/token`` but cannot act on the question API directly.
    """
    role_accounts = role_accounts or {}

    async def token_handler(token: str):
        info = store.lookup(token)
        if info is not None:
            return {
                "uid": info.uid,
                "roleaccount": info.role_account,
                "pmcs": list(info.committees),
                "isRoot": info.is_root,
                "fullname": info.fullname,
                "metadata": {"scope": list(info.scopes)},
            }

        if role_accounts:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            credential = role_accounts.get(digest)
            if credential is not None:
                return {
                    "uid": credential.uid,
                    "roleaccount": True,
                    "pmcs": [],
                    "isRoot": False,
                    "fullname": credential.fullname,
                    "metadata": {"scope": [ROLE_ISSUE_SCOPE]},
                }

        return None

    return token_handler
