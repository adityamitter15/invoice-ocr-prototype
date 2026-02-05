import os
import re
import sqlite3
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

# -------------------------------------------------------------------
# Force-load backend/.env explicitly and override any shell variables
# -------------------------------------------------------------------
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

# Paths relative to the backend folder
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

SQLITE_DB_PATH = BACKEND_ROOT / "local.db"

# Prefer backend/db/schema_sqlite.sql, but also support repo-root db/schema_sqlite.sql
SQLITE_SCHEMA_PATH = BACKEND_ROOT / "db" / "schema_sqlite.sql"
SQLITE_SCHEMA_FALLBACK_PATH = REPO_ROOT / "db" / "schema_sqlite.sql"

ACTIVE_DB = {"engine": None, "mode": None, "detail": None}


def dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    """Return SQLite rows as plain dicts (FastAPI/Pydantic friendly)."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    """Create required tables for the prototype when using SQLite."""
    # Enforce FK constraints in SQLite
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass

    schema_path = SQLITE_SCHEMA_PATH if SQLITE_SCHEMA_PATH.exists() else SQLITE_SCHEMA_FALLBACK_PATH
    if not schema_path.exists():
        raise RuntimeError(
            f"SQLite schema missing. Looked for {SQLITE_SCHEMA_PATH} and {SQLITE_SCHEMA_FALLBACK_PATH}. "
            "Create a schema_sqlite.sql file for local fallback."
        )

    schema_sql = schema_path.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()


def _open_sqlite(db_path: Path, mode: str, detail: str) -> sqlite3.Connection:
    # check_same_thread=False makes sqlite usable in uvicorn reload/threaded contexts
    conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)

    # IMPORTANT: dict rows, not sqlite3.Row objects
    conn.row_factory = dict_factory

    _ensure_sqlite_schema(conn)
    ACTIVE_DB.update({"engine": "sqlite", "mode": mode, "detail": detail})
    return conn


if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Ensure backend/.env exists and is correct.")


def get_connection():
    # If env points to SQLite, use SQLite explicitly (no Postgres attempt)
    if DATABASE_URL.startswith("sqlite:///"):
        path = DATABASE_URL.replace("sqlite:///", "", 1)
        db_path = Path(path)
        if not db_path.is_absolute():
            db_path = (BACKEND_ROOT / db_path).resolve()
        return _open_sqlite(db_path, mode="explicit", detail=str(db_path))

    # Otherwise assume Postgres (Supabase) and try it first
    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            cursor_factory=RealDictCursor,
            connect_timeout=5,  # keep short so fallback is quick
            sslmode="require",
        )
        ACTIVE_DB.update({"engine": "postgres", "mode": "primary", "detail": "supabase"})
        return conn

    except psycopg2.OperationalError as e:
        # Automatic fallback to local SQLite (kept inside backend folder)
        return _open_sqlite(SQLITE_DB_PATH, mode="fallback", detail=str(e)[:160])


def is_sqlite_conn(conn) -> bool:
    return isinstance(conn, sqlite3.Connection)


def qmark(sql: str) -> str:
    """Convert Postgres-style SQL to SQLite-compatible SQL when needed."""
    # Replace Postgres placeholders with SQLite placeholders
    sql = sql.replace("%s", "?")

    # Strip Postgres-only JSON casts (SQLite doesn't support ::jsonb / ::json)
    sql = re.sub(r"::jsonb\b", "", sql)
    sql = re.sub(r"::json\b", "", sql)

    # SQLite doesn't support FOR UPDATE the same way
    sql = sql.replace("FOR UPDATE", "")

    return sql