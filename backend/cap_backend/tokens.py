"""Personal-access-token (bearer) store. See SPEC section 6.4.

Tokens are held entirely in process memory: they do not survive a restart,
and they are not shared between worker processes. Each issued token is
bound to one ASF UID, scoped exclusively to ``ask``, and expires 24 hours
after issuance. At most five tokens may be live for a single uid; issuing
a sixth evicts the oldest.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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


def build_token_handler(store: TokenStore):
    """Return an async function suitable for ``asfquart.APP.token_handler``.

    Per the asfquart sessions doc, the handler receives the raw bearer token
    and returns either ``None`` (unknown/expired) or a session-dict carrying
    the uid, committees, and ``metadata.scope`` list.
    """

    async def token_handler(token: str):
        info = store.lookup(token)
        if info is None:
            return None
        return {
            "uid": info.uid,
            "roleaccount": False,
            "pmcs": list(info.committees),
            "isRoot": info.is_root,
            "fullname": info.fullname,
            "metadata": {"scope": list(info.scopes)},
        }

    return token_handler
