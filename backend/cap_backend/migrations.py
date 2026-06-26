"""Versioned schema migration runner. See SPEC §7.

The schema is owned by an ordered set of numbered SQL files under
``cap_backend/sql/migrations`` (``0001_*.sql``, ``0002_*.sql``, ...). Applied
versions are tracked in a ``schema_migrations`` table so the runner can bring
*any* database (fresh, legacy, or partially migrated) up to the latest schema
on startup. This is the standing mechanism for every future schema change:
new columns, tables, constraints, or data fix-ups ship as a new migration file
with the next version number, never as an edit to an already-released one.

Bootstrapping rules:

* **Fresh database** (no core tables yet): every migration runs in order, so
  the database is built from ``0001`` forward.
* **Legacy database** (created before this runner, so the ``questions`` table
  exists but there is no ``schema_migrations`` table): its on-disk schema is by
  definition the ``0001`` baseline, so ``0001`` is *stamped* as applied without
  re-running it, and every later migration runs to upgrade it.
* **Already-migrated database**: only versions absent from
  ``schema_migrations`` run.

Each migration runs inside a single transaction together with the bookkeeping
``INSERT`` into ``schema_migrations``, so applying a migration is atomic: it
either fully lands and is recorded, or it rolls back and is retried next start.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources

# Package directory (a resource subdirectory of ``cap_backend.sql``) that holds
# the numbered migration files.
_MIGRATIONS_PACKAGE = "cap_backend.sql"
_MIGRATIONS_DIRNAME = "migrations"

# A migration filename is ``<zero-padded-version>_<slug>.sql``.
_MIGRATION_RE = re.compile(r"^(\d+)_(.+)\.sql$")

# A core table that has existed since the 0001 baseline. Its presence without a
# ``schema_migrations`` table is what marks a pre-runner (legacy) database.
_BASELINE_SENTINEL_TABLE = "questions"


@dataclass(frozen=True)
class Migration:
    """One discovered migration file."""

    version: int
    name: str  # filename without the ``.sql`` suffix, e.g. ``0001_initial_schema``
    sql: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def discover_migrations() -> list[Migration]:
    """Return every bundled migration, ordered by ascending version.

    Raises ``ValueError`` if two files share a version or the version sequence
    is not the contiguous ``1, 2, 3, ...`` the runner relies on.
    """
    directory = resources.files(_MIGRATIONS_PACKAGE).joinpath(_MIGRATIONS_DIRNAME)
    migrations: list[Migration] = []
    for entry in directory.iterdir():
        match = _MIGRATION_RE.match(entry.name)
        if match is None:
            continue
        version = int(match.group(1))
        migrations.append(
            Migration(
                version=version,
                name=entry.name[: -len(".sql")],
                sql=entry.read_text(encoding="utf-8"),
            )
        )

    migrations.sort(key=lambda m: m.version)
    versions = [m.version for m in migrations]
    if len(set(versions)) != len(versions):
        raise ValueError(f"Duplicate migration version among {versions}")
    if versions and versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"Migration versions must be contiguous from 1; got {versions}")
    return migrations


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            applied_at  TEXT NOT NULL
        )
        """
    )


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row[0]) for row in rows}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _stamp(conn: sqlite3.Connection, migration: Migration) -> None:
    """Record a migration as applied without running its SQL (baseline)."""
    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (migration.version, migration.name, _now_iso()),
    )


def _apply(conn: sqlite3.Connection, migration: Migration) -> None:
    """Run one migration and record it, atomically.

    The connection is in autocommit mode (``isolation_level=None``), so the
    migration SQL and its bookkeeping insert are wrapped in an explicit
    ``BEGIN``/``COMMIT`` and executed as a single script. ``executescript``
    performs no implicit transaction control of its own beyond an initial
    commit of any pending work, so the wrapping transaction is what makes the
    whole migration atomic.
    """
    # ``executescript`` cannot bind parameters, so the bookkeeping row is
    # inlined. The values are safe: ``version`` is an int, ``applied_at`` is a
    # server-generated timestamp, and the migration name comes from a filename
    # constrained by ``_MIGRATION_RE`` (no quotes). Escape defensively anyway.
    name = migration.name.replace("'", "''")
    bookkeeping = (
        "INSERT INTO schema_migrations (version, name, applied_at) "
        f"VALUES ({migration.version}, '{name}', '{_now_iso()}');"
    )
    script = f"BEGIN;\n{migration.sql}\n{bookkeeping}\nCOMMIT;"
    try:
        conn.executescript(script)
    except Exception:
        # A statement failed with the transaction still open; undo the partial
        # migration so the next startup can retry from a clean state.
        try:
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        raise


def run_migrations(conn: sqlite3.Connection) -> list[int]:
    """Bring ``conn`` up to the latest schema. Returns the versions applied now.

    Safe to call on every startup: it is a no-op once the database is current.
    """
    migrations = discover_migrations()
    _ensure_migrations_table(conn)
    applied = _applied_versions(conn)

    # Baseline a legacy database: tables exist but nothing is recorded, so the
    # on-disk schema is the 0001 shape. Stamp 0001 as applied (do not re-run
    # it) and let later migrations upgrade from there.
    if not applied and migrations and _table_exists(conn, _BASELINE_SENTINEL_TABLE):
        baseline = migrations[0]
        _stamp(conn, baseline)
        applied.add(baseline.version)

    newly_applied: list[int] = []
    for migration in migrations:
        if migration.version in applied:
            continue
        _apply(conn, migration)
        newly_applied.append(migration.version)
    return newly_applied
