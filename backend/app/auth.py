"""Manager authentication: bcrypt hashing, JWT sessions, brute-force throttle."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import string
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import bcrypt
import jwt
from fastapi import Header, HTTPException, Request, status

from app.database import get_connection, is_sqlite_conn, qmark


JWT_ALGORITHM = "HS256"
DEFAULT_TOKEN_TTL_HOURS = 8
REMEMBER_ME_TTL_HOURS = 24 * 7

BCRYPT_COST = int(os.getenv("BCRYPT_COST", "12"))

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128

# NIST 800-63B recommends rejecting breach-corpus passwords. A compact
# in-repo list avoids a network dependency for this prototype.
_COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "passw0rd", "qwerty",
    "qwerty123", "123456", "12345678", "1234567890", "111111", "000000",
    "letmein", "welcome", "admin", "admin123", "root", "toor", "iloveyou",
    "monkey", "dragon", "baseball", "football", "superman", "batman",
    "princess", "sunshine", "master", "shadow", "michael", "changeme",
})

_LOCKOUT_WINDOW_SECONDS = 15 * 60
_LOCKOUT_MAX_ATTEMPTS = 5

_attempts_lock = threading.Lock()
_failed_attempts: Dict[str, list[float]] = {}


def _env_secret() -> str:
    secret = os.getenv("AUTH_SECRET")
    if not secret or len(secret) < 32:
        raise RuntimeError(
            "AUTH_SECRET must be set to a high-entropy value of at least 32 characters."
        )
    return secret


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(BCRYPT_COST)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# Used as a timing-equalisation target when no real hash is on file.
_DUMMY_HASH = bcrypt.hashpw(secrets.token_urlsafe(32).encode("utf-8"), bcrypt.gensalt(BCRYPT_COST)).decode("utf-8")


def constant_time_bcrypt_check(plain: str, hashed: Optional[str]) -> bool:
    """Verify `plain` against `hashed`, keeping timing equal when `hashed` is None."""
    target = hashed or _DUMMY_HASH
    result = verify_password(plain, target)
    return bool(hashed) and result


def evaluate_password_rules(password: str) -> List[Dict[str, Any]]:
    """Return the per-rule status shared between UI checklist and server."""
    return [
        {"id": "length", "label": f"At least {MIN_PASSWORD_LENGTH} characters", "passed": len(password) >= MIN_PASSWORD_LENGTH},
        {"id": "upper", "label": "An uppercase letter (A-Z)", "passed": bool(re.search(r"[A-Z]", password))},
        {"id": "lower", "label": "A lowercase letter (a-z)", "passed": bool(re.search(r"[a-z]", password))},
        {"id": "digit", "label": "A number (0-9)", "passed": bool(re.search(r"\d", password))},
        {"id": "symbol", "label": "A special character", "passed": bool(re.search(r"[^A-Za-z0-9]", password))},
        {"id": "common", "label": "Not a commonly used password", "passed": bool(password) and password.lower() not in _COMMON_PASSWORDS},
    ]


def validate_password_policy(password: str) -> Tuple[bool, Optional[str]]:
    """NIST 800-63B length floor plus the composition rules advertised in the UI."""
    if not password:
        return False, "Password must not be empty."
    if len(password) > MAX_PASSWORD_LENGTH:
        return False, f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    for rule in evaluate_password_rules(password):
        if not rule["passed"]:
            return False, f"Password is missing: {rule['label'].lower()}."
    return True, None


# Recovery codes: a 16-character single-use code shown to the user once so they
# can reset their password without access to the email inbox.

_RECOVERY_ALPHABET = string.ascii_uppercase + string.digits
_RECOVERY_LENGTH = 16


def generate_recovery_code() -> str:
    """Return a 16-character recovery code formatted as 4 blocks of 4."""
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_LENGTH))
    return "-".join(raw[i : i + 4] for i in range(0, _RECOVERY_LENGTH, 4))


def normalise_recovery_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


# Email reset tokens: high-entropy tokens emailed to the user via Resend.
# Stored only as a SHA-256 hash in password_reset_tokens; short TTL.

RESET_TOKEN_TTL_MINUTES = 15
RESET_TOKEN_BYTES = 32


def generate_reset_token() -> str:
    return secrets.token_urlsafe(RESET_TOKEN_BYTES)


def hash_reset_token(token: str) -> str:
    # SHA-256 rather than bcrypt: tokens already carry 256 bits of entropy and
    # expire within minutes, so a fast hash is the right primitive here.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _prune_attempts(bucket: list[float], now: float) -> list[float]:
    cutoff = now - _LOCKOUT_WINDOW_SECONDS
    return [t for t in bucket if t >= cutoff]


def register_failed_attempt(client_key: str) -> None:
    now = time.monotonic()
    with _attempts_lock:
        bucket = _prune_attempts(_failed_attempts.get(client_key, []), now)
        bucket.append(now)
        _failed_attempts[client_key] = bucket


def clear_failed_attempts(client_key: str) -> None:
    with _attempts_lock:
        _failed_attempts.pop(client_key, None)


def is_locked_out(client_key: str) -> bool:
    now = time.monotonic()
    with _attempts_lock:
        bucket = _prune_attempts(_failed_attempts.get(client_key, []), now)
        _failed_attempts[client_key] = bucket
        return len(bucket) >= _LOCKOUT_MAX_ATTEMPTS


def client_key_from_request(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def create_access_token(subject: str, *, remember: bool = False) -> Tuple[str, datetime]:
    ttl_hours = REMEMBER_ME_TTL_HOURS if remember else DEFAULT_TOKEN_TTL_HOURS
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=ttl_hours)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "role": "manager",
    }
    token = jwt.encode(payload, _env_secret(), algorithm=JWT_ALGORITHM)
    return token, expires


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, _env_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def lookup_user(username: Optional[str], *, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        if user_id is not None:
            cur.execute(
                qmark(
                    "SELECT id, username, password_hash, recovery_code_hash, email, role, "
                    "last_login_at, password_changed_at "
                    "FROM users WHERE id = %s",
                    conn,
                ),
                (user_id,),
            )
        else:
            cur.execute(
                qmark(
                    "SELECT id, username, password_hash, recovery_code_hash, email, role, "
                    "last_login_at, password_changed_at "
                    "FROM users WHERE username = %s",
                    conn,
                ),
                (username,),
            )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        conn.close()


def touch_last_login(user_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        now_fn = "datetime('now')" if is_sqlite_conn(conn) else "NOW()"
        cur.execute(
            qmark(f"UPDATE users SET last_login_at = {now_fn} WHERE id = %s", conn),
            (user_id,),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


def require_manager(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """FastAPI dependency that authenticates a manager bearer token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if payload.get("role") != "manager":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient privileges",
        )
    return payload
