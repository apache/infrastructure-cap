"""Schema migration runner tests. See SPEC §7."""

from __future__ import annotations

import sqlite3

import pytest

from cap_backend.db import connect, read_schema_sql
from cap_backend.migrations import discover_migrations, run_migrations


def _schema_objects(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Return (type, name, normalized-sql) for every user object.

    ``schema_migrations`` (runner bookkeeping) and SQLite's internal objects
    are excluded so a migration-built schema can be compared to the snapshot.
    """
    rows = conn.execute(
        """
        SELECT type, name, sql FROM sqlite_master
         WHERE name NOT LIKE 'sqlite_%'
           AND name != 'schema_migrations'
         ORDER BY type, name
        """
    ).fetchall()
    return [(r[0], r[1], (r[2] or "").strip()) for r in rows]


def _mem() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_discover_migrations_is_contiguous_and_sorted():
    migrations = discover_migrations()
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "0001_initial_schema"


def test_fresh_database_runs_all_migrations():
    conn = _mem()
    applied = run_migrations(conn)
    expected = [m.version for m in discover_migrations()]
    assert applied == expected
    recorded = [int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations")]
    assert recorded == expected


def test_run_migrations_is_idempotent():
    conn = _mem()
    run_migrations(conn)
    # A second run on an up-to-date database applies nothing.
    assert run_migrations(conn) == []


def test_migrations_match_schema_snapshot():
    """Applying every migration must yield the same schema as schema.sql."""
    migrated = _mem()
    run_migrations(migrated)

    snapshot = _mem()
    snapshot.executescript(read_schema_sql())

    assert _schema_objects(migrated) == _schema_objects(snapshot)


def test_legacy_database_is_baselined_and_upgraded():
    """A pre-runner DB (0001 schema, no schema_migrations) upgrades in place."""
    conn = _mem()
    # Simulate a legacy install: only the initial schema, applied directly.
    conn.executescript(discover_migrations()[0].sql)
    # It must reject the new action before migrating.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO audit_log (occurred_at, actor, action) VALUES ('t', 'u', 'token.issue')"
        )
    # Seed an existing audit row to prove the rebuild preserves data.
    conn.execute(
        "INSERT INTO audit_log (occurred_at, actor, action, question_id) "
        "VALUES ('t', 'u', 'question.create', 7)"
    )

    applied = run_migrations(conn)
    # 0001 is stamped (not re-run); every later migration executes.
    assert applied == [2, 3]
    recorded = [int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations")]
    assert recorded == [1, 2, 3]

    # The widened constraint now accepts token.issue, and the old row survived.
    conn.execute(
        "INSERT INTO audit_log (occurred_at, actor, action) VALUES ('t', 'u', 'token.issue')"
    )
    surviving = conn.execute(
        "SELECT question_id FROM audit_log WHERE action = 'question.create'"
    ).fetchone()
    assert surviving["question_id"] == 7


def test_0003_maps_is_binding_to_binding_scope_and_keeps_responses():
    """0003 rebuilds `questions`; question and response rows must survive.

    The rebuild renames the parent table aside, which re-points the child
    table's REFERENCES clause at it. If the child were not rebuilt first,
    dropping the old parent would cascade every response away.
    """
    conn = _mem()
    # Foreign keys are ON in production (db.py), which is what makes the
    # cascade hazard real, so enforce them here too.
    conn.execute("PRAGMA foreign_keys = ON")
    # A legacy (0001-shaped) database with one question per old is_binding
    # value, each carrying a response.
    conn.executescript(discover_migrations()[0].sql)
    for qid, is_binding in ((1, 1), (2, 0)):
        conn.execute(
            """
            INSERT INTO questions (
                question_id, request_id, project_id, title, description, requester,
                target_audience, approval_type, response_option_json, is_binding,
                is_private, closes_at, created_at, updated_at
            ) VALUES (?, ?, 'seapony', 't', 'd', 'carol', 'PMC: Apache SeaPony',
                      'majority_approval', '{"kind":"vote"}', ?, 0, 't', 't', 't')
            """,
            (qid, f"req_{qid}", is_binding),
        )
        conn.execute(
            """
            INSERT INTO responses (
                response_id, question_id, voter, response_kind, response_json,
                is_binding, is_veto, created_at, updated_at
            ) VALUES (?, ?, 'dave', 'vote', '{"kind":"vote","value":"+1"}', 1, 0, 't', 't')
            """,
            (f"resp_{qid}", qid),
        )
    conn.commit()

    assert run_migrations(conn) == [2, 3]

    # Both old values land on the committee-only default.
    rows = conn.execute(
        "SELECT question_id, binding_scope FROM questions ORDER BY question_id"
    ).fetchall()
    assert [(r["question_id"], r["binding_scope"]) for r in rows] == [
        (1, "committee"),
        (2, "committee"),
    ]
    # The response history is intact and its per-vote snapshot untouched.
    responses = conn.execute(
        "SELECT response_id, question_id, is_binding FROM responses ORDER BY response_id"
    ).fetchall()
    assert [(r["response_id"], r["question_id"], r["is_binding"]) for r in responses] == [
        ("resp_1", 1, 1),
        ("resp_2", 2, 1),
    ]
    # The rebuilt child still points at the rebuilt parent, and the CHECK
    # constraint on the new column is live.
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE questions SET binding_scope = 'everyone' WHERE question_id = 1")


def test_partially_migrated_database_runs_only_missing():
    conn = _mem()
    # Pretend only 0001 ran (fresh-then-stamped state).
    conn.executescript(discover_migrations()[0].sql)
    conn.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
    )
    conn.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (1, '0001', 't')"
    )

    applied = run_migrations(conn)
    assert applied == [2, 3]


def test_migration_failure_rolls_back(tmp_path, monkeypatch):
    """A failing migration leaves no partial state and is not recorded."""
    import cap_backend.migrations as mig

    real = mig.discover_migrations()
    broken = mig.Migration(version=99, name="0099_broken", sql="CREATE TABLE bad (id INT;")
    monkeypatch.setattr(mig, "discover_migrations", lambda: [*real, broken])

    conn = _mem()
    with pytest.raises(sqlite3.OperationalError):
        run_migrations(conn)

    # The good migrations committed; the broken one neither created its table
    # nor recorded a row.
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "bad" not in tables
    recorded = {int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations")}
    assert 99 not in recorded


def test_connect_then_migrate_round_trip(tmp_path):
    """End-to-end: a real on-disk connection migrates and is queryable."""
    db_path = tmp_path / "cap.sqlite3"
    conn = connect(db_path)
    try:
        run_migrations(conn)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "questions",
            "responses",
            "audit_log",
            "pubsub_cursor",
            "schema_migrations",
        } <= names
    finally:
        conn.close()
