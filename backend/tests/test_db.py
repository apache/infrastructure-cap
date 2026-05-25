"""Database schema-bootstrap and audit-log smoke tests."""

from __future__ import annotations

import sqlite3

from cap_backend.audit import record
from cap_backend.db import Database, bootstrap_schema, read_schema_sql


def test_schema_sql_loadable():
    sql = read_schema_sql()
    assert "CREATE TABLE IF NOT EXISTS questions" in sql
    assert "CREATE TABLE IF NOT EXISTS responses" in sql
    assert "CREATE TABLE IF NOT EXISTS audit_log" in sql


def test_bootstrap_creates_all_tables(tmp_path):
    db_path = tmp_path / "cap.sqlite3"
    conn = sqlite3.connect(str(db_path))
    bootstrap_schema(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"questions", "responses", "audit_log", "pubsub_cursor"} <= names


def test_bootstrap_is_idempotent(tmp_path):
    db_path = tmp_path / "cap.sqlite3"
    conn = sqlite3.connect(str(db_path))
    bootstrap_schema(conn)
    bootstrap_schema(conn)
    # The pubsub_cursor row must remain a singleton thanks to the unique CHECK.
    rows = conn.execute("SELECT id, last_audit_id FROM pubsub_cursor").fetchall()
    assert rows == [(1, 0)]


def test_audit_record_appends_row(tmp_path):
    db_path = tmp_path / "cap.sqlite3"
    database = Database(db_path)
    try:
        audit_id = record(
            database.conn,
            action="question.create",
            actor="carol",
            question_id=42,
            details={"after": {"title": "x"}},
        )
        assert audit_id == 1
        row = database.conn.execute(
            "SELECT action, actor, question_id, details_json FROM audit_log WHERE audit_id = ?",
            (audit_id,),
        ).fetchone()
        assert row["action"] == "question.create"
        assert row["actor"] == "carol"
        assert row["question_id"] == 42
        assert '"title"' in row["details_json"]
    finally:
        database.close()


def test_audit_action_constraint_rejects_unknown(tmp_path):
    db_path = tmp_path / "cap.sqlite3"
    database = Database(db_path)
    try:
        try:
            database.conn.execute(
                "INSERT INTO audit_log (occurred_at, actor, action) VALUES (?, ?, ?)",
                ("2026-01-01T00:00:00Z", "alice", "question.invented"),
            )
        except sqlite3.IntegrityError:
            return
        raise AssertionError("Expected CHECK violation on unknown audit action")
    finally:
        database.close()
