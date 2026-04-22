"""Bootstrap (or reset) the manager account from environment variables.

The credentials are read from backend/.env so that they never enter the source
tree. Running this script is idempotent: an existing account with the same
username has its password hash replaced.

Usage
-----
    python -m scripts.seed_manager

Required environment variables (set in backend/.env):
    MANAGER_USERNAME   Desired manager username.
    MANAGER_PASSWORD   Plaintext password. Consumed once and hashed with bcrypt.
                       Safe to remove from .env afterwards; the hash in the
                       database is the only long-lived copy.
    AUTH_SECRET        Unrelated to this script, but required by the running
                       backend. Generate with secrets.token_urlsafe(64).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running as a plain script (python backend/scripts/seed_manager.py) by
# adding the backend directory to sys.path.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(dotenv_path=BACKEND_ROOT / ".env", override=True)

from app.auth import (  # noqa: E402
    generate_recovery_code,
    hash_password,
    normalise_recovery_code,
    validate_password_policy,
)
from app.database import get_connection, is_sqlite_conn  # noqa: E402


def main() -> int:
    username = (os.getenv("MANAGER_USERNAME") or "").strip()
    password = os.getenv("MANAGER_PASSWORD") or ""
    email = (os.getenv("MANAGER_EMAIL") or "").strip() or None

    if not username or not password:
        print(
            "MANAGER_USERNAME and MANAGER_PASSWORD must be set in backend/.env.",
            file=sys.stderr,
        )
        return 2

    ok, reason = validate_password_policy(password)
    if not ok:
        print(f"Password rejected: {reason}", file=sys.stderr)
        return 2

    password_hash = hash_password(password)
    recovery_code = generate_recovery_code()
    recovery_hash = hash_password(normalise_recovery_code(recovery_code))

    conn = get_connection()
    try:
        cur = conn.cursor()
        ph = "?" if is_sqlite_conn(conn) else "%s"
        cur.execute(f"SELECT id FROM users WHERE username = {ph}", (username,))
        existing = cur.fetchone()

        if existing:
            if is_sqlite_conn(conn):
                cur.execute(
                    "UPDATE users SET password_hash = ?, recovery_code_hash = ?, "
                    "email = ?, password_changed_at = datetime('now') WHERE username = ?",
                    (password_hash, recovery_hash, email, username),
                )
            else:
                cur.execute(
                    "UPDATE users SET password_hash = %s, recovery_code_hash = %s, "
                    "email = %s, password_changed_at = NOW() WHERE username = %s",
                    (password_hash, recovery_hash, email, username),
                )
            action = "updated"
        elif is_sqlite_conn(conn):
            cur.execute(
                "INSERT INTO users (username, password_hash, recovery_code_hash, email, role, "
                "password_changed_at) VALUES (?, ?, ?, ?, 'manager', datetime('now'))",
                (username, password_hash, recovery_hash, email),
            )
            action = "created"
        else:
            cur.execute(
                "INSERT INTO users (username, password_hash, recovery_code_hash, email, role, "
                "password_changed_at) VALUES (%s, %s, %s, %s, 'manager', NOW())",
                (username, password_hash, recovery_hash, email),
            )
            action = "created"

        conn.commit()
        cur.close()
    finally:
        conn.close()

    print(f"Manager account '{username}' {action}.")
    if email:
        print(f"Reset emails will be delivered to: {email}")
    else:
        print("No MANAGER_EMAIL set; email-based reset is disabled for this account.")
    print("")
    print("RECOVERY CODE (store this securely, it is shown only once):")
    print(f"    {recovery_code}")
    print("")
    print("The code is stored only as a bcrypt hash in users.recovery_code_hash.")
    print("You may now remove MANAGER_PASSWORD from backend/.env if you wish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
