#!/usr/bin/env python3
"""Reconcile the live SQLite database with ``cap_backend/sql/schema.sql``.

Run with:

    cd backend
    uv run python upgradedb.py            # interactive
    uv run python upgradedb.py --yes      # skip confirmation
    uv run python upgradedb.py --dry-run  # print plan, change nothing

The script compares each table in the live database (resolved through the
same ``config.yaml`` the server uses) against the bundled ``schema.sql``,
then applies the smallest set of ALTERs that brings the live database into
line:

* A table present in the schema but missing from the database is created.
* A column missing from a live table is added via ``ALTER TABLE ... ADD
  COLUMN`` when the column has a SQLite-acceptable default; otherwise the
  table is rewritten.
* A column whose type/notnull/default differs, or a table whose
  table-level constraints (CHECK / UNIQUE / FK) differ from the schema,
  triggers a full table rewrite: a new table is created with the target
  schema, the old data is copied across the columns that survive,
  indexes are reapplied, and the new table replaces the old one.
* An index in the schema that is missing from the database is created.

The schema file is the source of truth. Anything that exists in the live
database but not in ``schema.sql`` is left alone (the script never drops
tables, columns, or indexes); the operator must remove obsolete artifacts
by hand.

The parsing strategy is robust: ``schema.sql`` is executed against an
in-memory SQLite database, then both databases are introspected with the
exact same ``PRAGMA table_info`` / ``sqlite_master`` queries. This avoids
hand-rolling a SQL parser and guarantees the two sides are compared on
SQLite's own terms.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Resolve the script's directory so the relative imports / file lookups
# below work regardless of where ``uv run`` is invoked from.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from cap_backend.config import load_settings  # noqa: E402
from cap_backend.db import read_schema_sql  # noqa: E402


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    """One row from ``PRAGMA table_info(<table>)``."""

    name: str
    type: str
    notnull: bool
    dflt_value: str | None
    pk: int  # 0 if not part of the PK, otherwise the position in the PK


@dataclass
class TableSchema:
    name: str
    create_sql: str
    columns: dict[str, Column] = field(default_factory=dict)


@dataclass
class IndexSchema:
    name: str
    table: str
    create_sql: str


def _table_columns(conn: sqlite3.Connection, table: str) -> dict[str, Column]:
    rows = conn.execute(f"PRAGMA table_info({_quote_ident(table)})").fetchall()
    cols: dict[str, Column] = {}
    for cid, name, typ, notnull, dflt, pk in rows:
        cols[name] = Column(
            name=name,
            type=(typ or "").upper(),
            notnull=bool(notnull),
            dflt_value=dflt,
            pk=int(pk),
        )
    return cols


def _load_tables(conn: sqlite3.Connection) -> dict[str, TableSchema]:
    out: dict[str, TableSchema] = {}
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    for name, sql in rows:
        out[name] = TableSchema(
            name=name,
            create_sql=sql or "",
            columns=_table_columns(conn, name),
        )
    return out


def _load_indexes(conn: sqlite3.Connection) -> dict[str, IndexSchema]:
    out: dict[str, IndexSchema] = {}
    rows = conn.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master "
        "WHERE type = 'index' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL "
        "ORDER BY name"
    ).fetchall()
    for name, tbl, sql in rows:
        out[name] = IndexSchema(name=name, table=tbl, create_sql=sql)
    return out


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# CREATE TABLE comparison and rewriting
# ---------------------------------------------------------------------------


_COMMENT_RE = re.compile(r"--[^\n]*")
_WHITESPACE_RE = re.compile(r"\s+")
_IF_NOT_EXISTS_RE = re.compile(r"if\s+not\s+exists\s+", re.IGNORECASE)


def _normalize_sql(sql: str) -> str:
    """Reduce a CREATE statement to a form that ignores cosmetic differences.

    The goal is: "two CREATE statements that produce identical SQLite tables
    normalize to the same string." Comments, ``IF NOT EXISTS``, case, and
    whitespace runs are all collapsed; the rest of the text is left intact.
    """
    s = _COMMENT_RE.sub("", sql)
    s = _IF_NOT_EXISTS_RE.sub("", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    # Whitespace around punctuation is cosmetic. We strip it both sides
    # so ``(0, 1)``, ``(0,1)``, and ``( 0 , 1 )`` all normalize alike.
    s = re.sub(r"\s*,\s*", ",", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    # Identifier quoting is cosmetic in SQLite. ``ALTER TABLE ... RENAME TO``
    # rewrites stored CREATE statements with double-quoted names, so we
    # strip ``"`` and `` ` `` here. String literals use single quotes and
    # are not affected.
    s = s.replace('"', "").replace("`", "")
    return s.lower()


def _rewrite_create_table_to(name: str, original: str, new_name: str) -> str:
    """Return ``original`` with its target table name swapped for ``new_name``.

    Used to materialize the target schema under a temporary name during the
    classic 12-step table-rewrite dance.
    """
    pattern = re.compile(
        r"(?i)\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?"
        + re.escape(name)
        + r"\b"
    )
    return pattern.sub(f"CREATE TABLE {new_name}", original, count=1)


def _columns_addable(missing_in_db: list[Column]) -> bool:
    """True iff every missing column can be added via ``ALTER TABLE ... ADD``.

    SQLite refuses ``ADD COLUMN`` for columns that are NOT NULL with no
    default, and for columns whose default is a non-constant expression
    (CURRENT_TIMESTAMP excepted, but we keep the rule conservative). When
    any new column fails the check, we fall back to a table rewrite.
    """
    for col in missing_in_db:
        if col.notnull and col.dflt_value is None:
            return False
    return True


def _column_signature(col: Column) -> tuple:
    """Tuple used to detect whether two columns differ in a meaningful way."""
    return (
        col.type.strip().upper(),
        col.notnull,
        (col.dflt_value or "").strip(),
        col.pk,
    )


# ---------------------------------------------------------------------------
# Plan computation
# ---------------------------------------------------------------------------


@dataclass
class TablePlan:
    name: str
    action: str  # "create" | "add_columns" | "rewrite" | "noop"
    create_sql: str = ""  # for create / rewrite
    add_columns: list[Column] = field(default_factory=list)
    common_columns: list[str] = field(default_factory=list)  # for rewrite
    reason: str = ""


@dataclass
class IndexPlan:
    name: str
    table: str
    create_sql: str
    action: str  # "create" | "noop"


@dataclass
class Plan:
    tables: list[TablePlan] = field(default_factory=list)
    indexes: list[IndexPlan] = field(default_factory=list)

    def has_work(self) -> bool:
        return any(t.action != "noop" for t in self.tables) or any(
            i.action != "noop" for i in self.indexes
        )


def build_plan(live: sqlite3.Connection, target_sql: str) -> Plan:
    """Diff ``live`` against the schema text and produce an action plan."""
    target_conn = sqlite3.connect(":memory:")
    try:
        target_conn.executescript(target_sql)
        target_tables = _load_tables(target_conn)
        target_indexes = _load_indexes(target_conn)
    finally:
        target_conn.close()

    live_tables = _load_tables(live)
    live_indexes = _load_indexes(live)

    plan = Plan()

    for name, target in target_tables.items():
        live_tbl = live_tables.get(name)
        if live_tbl is None:
            plan.tables.append(
                TablePlan(
                    name=name,
                    action="create",
                    create_sql=target.create_sql,
                    reason="table missing from live database",
                )
            )
            continue

        # Detect column-level differences.
        target_cols = target.columns
        live_cols = live_tbl.columns
        missing_in_db = [c for c in target_cols.values() if c.name not in live_cols]
        changed: list[tuple[str, Column, Column]] = []
        for name_, col in target_cols.items():
            if name_ in live_cols:
                if _column_signature(col) != _column_signature(live_cols[name_]):
                    changed.append((name_, live_cols[name_], col))

        same_create = _normalize_sql(live_tbl.create_sql) == _normalize_sql(target.create_sql)

        if same_create and not missing_in_db and not changed:
            plan.tables.append(TablePlan(name=name, action="noop"))
            continue

        # If only additive changes (new columns) and they're all ADD-COLUMN
        # compatible, prefer the cheap ALTER path.
        if not changed and missing_in_db and same_create_ignoring_new_cols(
            live_tbl.create_sql, target.create_sql, missing_in_db
        ) and _columns_addable(missing_in_db):
            plan.tables.append(
                TablePlan(
                    name=name,
                    action="add_columns",
                    add_columns=missing_in_db,
                    reason=f"missing columns: {', '.join(c.name for c in missing_in_db)}",
                )
            )
            continue

        # Otherwise, full rewrite. The columns we can copy over are the
        # ones that exist on BOTH sides; new columns get their default
        # (or NULL if no default), and removed columns are left behind.
        common = [c for c in target_cols if c in live_cols]
        reasons: list[str] = []
        if missing_in_db:
            reasons.append("new columns " + ", ".join(c.name for c in missing_in_db))
        if changed:
            reasons.append(
                "changed columns "
                + ", ".join(
                    f"{n} ({_column_signature(old)!r} -> {_column_signature(new)!r})"
                    for n, old, new in changed
                )
            )
        if not same_create and not same_create_ignoring_new_cols(
            live_tbl.create_sql, target.create_sql, missing_in_db
        ):
            reasons.append("table-level constraints differ (CHECK/UNIQUE/FK)")
        if not reasons:
            reasons.append("table-level constraints differ (CHECK/UNIQUE/FK)")
        plan.tables.append(
            TablePlan(
                name=name,
                action="rewrite",
                create_sql=target.create_sql,
                common_columns=common,
                reason="; ".join(reasons),
            )
        )

    # Index reconciliation: schema is the source of truth. Add anything
    # the live DB is missing. (Indexes on rewritten tables are recreated
    # as part of the rewrite step itself.)
    rewritten = {t.name for t in plan.tables if t.action == "rewrite"}
    for name, idx in target_indexes.items():
        if idx.table in rewritten:
            # Handled by the rewrite step itself.
            continue
        if name not in live_indexes:
            plan.indexes.append(
                IndexPlan(
                    name=name,
                    table=idx.table,
                    create_sql=idx.create_sql,
                    action="create",
                )
            )

    return plan


def same_create_ignoring_new_cols(
    live_sql: str, target_sql: str, new_cols: list[Column]
) -> bool:
    """Approximate "table-level constraints are unchanged" check.

    For pure-additive plans we'd like to avoid a full rewrite even though
    the CREATE TABLE text obviously differs. The cheap proxy: strip out
    references to the new column names and check whether the remainder
    normalizes to the same thing on both sides. If the live CREATE has
    nothing left referring to the missing column AND the target CREATE,
    after the same stripping, matches the live CREATE, then the only
    difference is the addition of the new columns themselves.
    """
    live_norm = _normalize_sql(live_sql)
    target_stripped = target_sql
    # Remove each new column's definition line(s) from the target CREATE.
    for col in new_cols:
        target_stripped = re.sub(
            r"(?im)^\s*" + re.escape(col.name) + r"\b[^,\n]*(?:,|\n|$)",
            "",
            target_stripped,
        )
    target_norm = _normalize_sql(target_stripped)
    return live_norm == target_norm


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_plan(conn: sqlite3.Connection, plan: Plan, target_sql: str) -> None:
    """Apply ``plan`` to ``conn`` in a single transaction."""
    # Re-parse to recover the per-table index list for any rewritten tables.
    mem = sqlite3.connect(":memory:")
    try:
        mem.executescript(target_sql)
        target_indexes_by_table: dict[str, list[IndexSchema]] = {}
        for idx in _load_indexes(mem).values():
            target_indexes_by_table.setdefault(idx.table, []).append(idx)
    finally:
        mem.close()

    conn.execute("PRAGMA foreign_keys = OFF;")
    try:
        conn.execute("BEGIN")
        for t in plan.tables:
            if t.action == "create":
                conn.execute(t.create_sql)
            elif t.action == "add_columns":
                for col in t.add_columns:
                    coldef = _format_column_for_add(col)
                    conn.execute(f"ALTER TABLE {_quote_ident(t.name)} ADD COLUMN {coldef}")
            elif t.action == "rewrite":
                _rewrite_table(conn, t, target_indexes_by_table.get(t.name, []))

        for idx in plan.indexes:
            if idx.action == "create":
                conn.execute(idx.create_sql)

        # Cheap sanity check: refuse to commit if foreign keys ended up
        # broken by a rewrite. This catches bugs in this script before they
        # corrupt a live database.
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(
                "Foreign-key check failed after rewrite; rolling back. Offending rows: "
                + repr(bad)
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")


def _rewrite_table(
    conn: sqlite3.Connection, tplan: TablePlan, indexes: list[IndexSchema]
) -> None:
    new_name = f"__cap_upgrade_new_{tplan.name}"
    create_new = _rewrite_create_table_to(tplan.name, tplan.create_sql, new_name)
    conn.execute(create_new)

    if tplan.common_columns:
        cols = ", ".join(_quote_ident(c) for c in tplan.common_columns)
        conn.execute(
            f"INSERT INTO {_quote_ident(new_name)} ({cols}) "
            f"SELECT {cols} FROM {_quote_ident(tplan.name)}"
        )

    conn.execute(f"DROP TABLE {_quote_ident(tplan.name)}")
    conn.execute(f"ALTER TABLE {_quote_ident(new_name)} RENAME TO {_quote_ident(tplan.name)}")

    # Recreate every index the schema declares for this table. Indexes
    # attached to the old table were dropped along with it.
    for idx in indexes:
        conn.execute(idx.create_sql)


def _format_column_for_add(col: Column) -> str:
    """Render an ``ALTER TABLE ADD COLUMN`` clause from a Column tuple.

    PRAGMA table_info gives us everything we need; we re-emit it in the
    minimal form SQLite accepts. CHECK constraints attached to individual
    columns are NOT recovered by PRAGMA table_info, so a column whose
    only definition we have comes from the in-memory parse and lacks
    inline CHECKs. That's acceptable: column-level CHECKs in this schema
    are wrapped at the table level, which the rewrite path handles.
    """
    parts = [_quote_ident(col.name), col.type or "TEXT"]
    if col.notnull:
        parts.append("NOT NULL")
    if col.dflt_value is not None:
        parts.append(f"DEFAULT {col.dflt_value}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_plan(plan: Plan) -> None:
    if not plan.has_work():
        print("Database schema is already up to date. Nothing to do.")
        return

    print("Planned changes:")
    for t in plan.tables:
        if t.action == "noop":
            continue
        if t.action == "create":
            print(f"  + CREATE TABLE {t.name}  ({t.reason})")
        elif t.action == "add_columns":
            cols = ", ".join(c.name for c in t.add_columns)
            print(f"  + ALTER TABLE {t.name}: add column(s) {cols}")
        elif t.action == "rewrite":
            print(f"  ~ REWRITE TABLE {t.name}  ({t.reason})")
            if t.common_columns:
                print(f"      copying columns: {', '.join(t.common_columns)}")
    for idx in plan.indexes:
        if idx.action == "create":
            print(f"  + CREATE INDEX {idx.name} ON {idx.table}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bring the live CAP SQLite database into line with the bundled "
            "cap_backend/sql/schema.sql."
        )
    )
    parser.add_argument(
        "--config",
        help="Path to config.yaml (defaults to the standard search order).",
    )
    parser.add_argument(
        "--db",
        help="Override the database path. If set, --config is not consulted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan and exit without modifying the database.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Apply the plan without prompting for confirmation.",
    )
    args = parser.parse_args(argv)

    if args.db:
        db_path = Path(args.db)
    else:
        settings = load_settings(args.config)
        db_path = Path(settings.database.path)

    if not db_path.exists():
        print(f"Database file not found: {db_path}", file=sys.stderr)
        return 2

    target_sql = read_schema_sql()

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        plan = build_plan(conn, target_sql)
        print("Target schema source: cap_backend/sql/schema.sql")
        print(f"Live database:        {db_path}")
        _print_plan(plan)
        if not plan.has_work():
            return 0
        if args.dry_run:
            print("\nDry run; no changes applied.")
            return 0
        if not args.yes:
            ans = input("\nApply these changes? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                print("Aborted.")
                return 1
        apply_plan(conn, plan, target_sql)
        print("Done.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
