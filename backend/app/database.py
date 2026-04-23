"""Database connection handling with Postgres -> SQLite fallback.

On startup the module probes Supabase Postgres with a 5-second wall-clock
timeout. If Postgres is reachable, every subsequent get_connection() opens
a real Postgres connection. If not, every connection opens local.db instead.
qmark() translates Postgres-flavoured SQL (%s placeholders, ::jsonb casts,
FOR UPDATE) into SQLite dialect at runtime so route handlers write the
query once.
"""

import logging
import os
import re
import sqlite3
import threading
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

SQLITE_DB_PATH = BACKEND_ROOT / "local.db"

SQLITE_SCHEMA_PATH = BACKEND_ROOT / "db" / "schema_sqlite.sql"
SQLITE_SCHEMA_FALLBACK_PATH = REPO_ROOT / "db" / "schema_sqlite.sql"

# Set on first successful probe or fallback; exposed via /health so operators
# can see which backend is actually serving requests.
ACTIVE_DB = {"engine": None, "mode": None, "detail": None}


def dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    """Return SQLite rows as plain dicts."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass

    schema_path = SQLITE_SCHEMA_PATH if SQLITE_SCHEMA_PATH.exists() else SQLITE_SCHEMA_FALLBACK_PATH
    if not schema_path.exists():
        raise RuntimeError(
            f"SQLite schema missing. Looked for {SQLITE_SCHEMA_PATH} and {SQLITE_SCHEMA_FALLBACK_PATH}."
        )

    schema_sql = schema_path.read_text(encoding="utf-8")
    conn.executescript(schema_sql)

    # Idempotent column upgrades for pre-existing SQLite databases.
    for alter in (
        "ALTER TABLE users ADD COLUMN recovery_code_hash TEXT",
        "ALTER TABLE users ADD COLUMN password_changed_at TEXT",
        "ALTER TABLE users ADD COLUMN email TEXT",
    ):
        try:
            conn.execute(alter)
        except sqlite3.OperationalError:
            pass

    # Audit log was added later; ensure existing databases pick it up.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY NOT NULL DEFAULT (
                lower(hex(randomblob(4))) || '-' ||
                lower(hex(randomblob(2))) || '-' ||
                lower(hex(randomblob(2))) || '-' ||
                lower(hex(randomblob(2))) || '-' ||
                lower(hex(randomblob(6)))
            ),
            user_id TEXT,
            action TEXT NOT NULL,
            subject_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    conn.commit()


def _open_sqlite(db_path: Path, mode: str, detail: str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10, check_same_thread=False)
    conn.row_factory = dict_factory
    _ensure_sqlite_schema(conn)
    ACTIVE_DB.update({"engine": "sqlite", "mode": mode, "detail": detail})
    return conn


if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Ensure backend/.env exists and is correct.")

# Startup probe: decide once which backend to use for the rest of the process.
_USE_SQLITE: bool

def _probe_postgres(url: str, timeout: float = 5.0) -> bool:
    # psycopg2's connect_timeout is ignored on macOS, so enforce it via thread join.
    result = [False]
    def _try():
        try:
            c = psycopg2.connect(url, cursor_factory=RealDictCursor,
                                 connect_timeout=5, sslmode="require")
            c.close()
            result[0] = True
        except Exception:
            pass
    t = threading.Thread(target=_try, daemon=True)
    t.start()
    t.join(timeout)
    return result[0]


if DATABASE_URL.startswith("sqlite:///"):
    _USE_SQLITE = True
elif _probe_postgres(DATABASE_URL):
    _USE_SQLITE = False
    ACTIVE_DB.update({"engine": "postgres", "mode": "primary", "detail": "supabase"})
    logger.info("Supabase reachable, using PostgreSQL")
else:
    _USE_SQLITE = True
    ACTIVE_DB.update({"engine": "sqlite", "mode": "fallback", "detail": "supabase unreachable"})
    logger.warning("Supabase unreachable, using local SQLite")


# Connection factory used by every route handler.
def get_connection():
    if _USE_SQLITE:
        if DATABASE_URL.startswith("sqlite:///"):
            path = DATABASE_URL.replace("sqlite:///", "", 1)
            db_path = Path(path)
            if not db_path.is_absolute():
                db_path = (BACKEND_ROOT / db_path).resolve()
            return _open_sqlite(db_path, mode="explicit", detail=str(db_path))
        return _open_sqlite(SQLITE_DB_PATH, mode="fallback", detail="supabase unreachable")

    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            cursor_factory=RealDictCursor,
            connect_timeout=5,
            sslmode="require",
        )
        ACTIVE_DB.update({"engine": "postgres", "mode": "primary", "detail": "supabase"})
        return conn
    except psycopg2.OperationalError as e:
        return _open_sqlite(SQLITE_DB_PATH, mode="fallback", detail=str(e)[:160])


def is_sqlite_conn(conn) -> bool:
    return isinstance(conn, sqlite3.Connection)


def qmark(sql: str, conn=None) -> str:
    """Adapt a SQL string to the active backend.

    Call sites write one Postgres-flavoured SQL string (``%s`` placeholders,
    ``::jsonb`` casts, ``FOR UPDATE``) and this helper rewrites it to the
    SQLite dialect when the runtime connection is SQLite. Passing ``conn``
    is preferred; when omitted the module-level ``_USE_SQLITE`` flag is used.
    """
    use_sqlite = is_sqlite_conn(conn) if conn is not None else _USE_SQLITE
    if not use_sqlite:
        return sql
    sql = sql.replace("%s", "?")
    sql = re.sub(r"::jsonb\b", "", sql)
    sql = re.sub(r"::json\b", "", sql)
    sql = sql.replace("FOR UPDATE", "")
    return sql
