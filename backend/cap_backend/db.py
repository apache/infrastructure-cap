"""SQLite connection helpers and schema bootstrap. See SPEC section 7."""

from __future__ import annotations

import asyncio
import sqlite3
from importlib import resources
from pathlib import Path

_SCHEMA_RESOURCE = ("cap_backend.sql", "schema.sql")


def read_schema_sql() -> str:
    """Return the bundled schema.sql contents."""
    package, name = _SCHEMA_RESOURCE
    return resources.files(package).joinpath(name).read_text(encoding="utf-8")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with the project's standard PRAGMAs applied."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def bootstrap_schema(conn: sqlite3.Connection) -> None:
    """Apply the bundled schema.sql to ``conn``.

    All statements are wrapped in ``CREATE ... IF NOT EXISTS``, so calling this
    against an already-initialized database is a safe no-op.
    """
    conn.executescript(read_schema_sql())


class Database:
    """Owns the shared SQLite connection and serializes writes.

    Per SPEC section 7, the service uses a single shared connection in WAL mode
    with writes serialized through an ``asyncio.Lock``. Reads do not need the
    lock; they can run concurrently on the same connection because SQLite in
    WAL mode tolerates concurrent readers with one writer.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = connect(self.path)
        bootstrap_schema(self.conn)
        self.write_lock = asyncio.Lock()

    def close(self) -> None:
        self.conn.close()
