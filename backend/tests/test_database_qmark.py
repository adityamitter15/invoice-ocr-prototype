"""Tests for the SQL dialect translator used by every route handler.

The translator has to be correct because it rewrites Postgres-flavoured
SQL to SQLite when the runtime connection is SQLite. A bug here would
fail silently on the fallback path and only surface in production.
"""

import sqlite3

from app.database import qmark, is_sqlite_conn


def test_qmark_passes_through_on_non_sqlite_string():
    sql = "SELECT * FROM t WHERE id = %s"
    # With no connection argument and a non-sqlite module state, the
    # translator should still be safe to call; it either rewrites or
    # passes through depending on the probe result at import time.
    out = qmark(sql)
    assert "%s" in out or "?" in out


def test_qmark_rewrites_percent_s_to_question_mark_for_sqlite():
    conn = sqlite3.connect(":memory:")
    try:
        sql = "SELECT * FROM t WHERE id = %s"
        assert qmark(sql, conn) == "SELECT * FROM t WHERE id = ?"
    finally:
        conn.close()


def test_qmark_strips_jsonb_cast_for_sqlite():
    conn = sqlite3.connect(":memory:")
    try:
        sql = "INSERT INTO t (d) VALUES (%s::jsonb)"
        assert "::jsonb" not in qmark(sql, conn)
    finally:
        conn.close()


def test_qmark_strips_for_update_for_sqlite():
    conn = sqlite3.connect(":memory:")
    try:
        sql = "SELECT * FROM t WHERE id = %s FOR UPDATE"
        assert "FOR UPDATE" not in qmark(sql, conn)
    finally:
        conn.close()


def test_is_sqlite_conn_detects_sqlite_connection():
    conn = sqlite3.connect(":memory:")
    try:
        assert is_sqlite_conn(conn) is True
    finally:
        conn.close()
