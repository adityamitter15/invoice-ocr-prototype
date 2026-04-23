"""FastAPI application for the AGW invoice OCR system.

Exposes the REST endpoints consumed by the React frontend: authentication
and password recovery, submission CRUD and approval, invoice and product
reads, analytics, and the image upload that runs the OCR pipeline.
"""

import io
import json
import logging
import os
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from app.schemas import InvoiceOut, ProductOut, SubmissionOut
from app.database import ACTIVE_DB, get_connection, is_sqlite_conn, qmark
from app.auth import (
    RESET_TOKEN_TTL_MINUTES,
    client_key_from_request,
    clear_failed_attempts,
    constant_time_bcrypt_check,
    create_access_token,
    evaluate_password_rules,
    generate_recovery_code,
    generate_reset_token,
    hash_password,
    hash_reset_token,
    is_locked_out,
    lookup_user,
    normalise_recovery_code,
    register_failed_attempt,
    require_manager,
    touch_last_login,
    validate_password_policy,
    verify_password,
)
from app.email import render_reset_email, send_email


# Each request gets a short id that is attached to every log line produced
# while handling it, so a single request can be followed across the log.
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        return True


_log_handler = logging.StreamHandler()
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s"
))
_log_handler.addFilter(_RequestIdFilter())
logging.basicConfig(level=logging.INFO, handlers=[_log_handler], force=True)

logger = logging.getLogger(__name__)

_STARTED_AT = datetime.now(timezone.utc)

app = FastAPI(
    title="AGW Invoice OCR API",
    description="Multi-engine OCR with human-in-the-loop review for handwritten invoices.",
    version="1.0.0",
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a short id to every request so log lines from the same request
    can be grouped together."""

    async def dispatch(self, request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        token = _request_id_ctx.set(rid)
        try:
            response = await call_next(request)
            response.headers["x-request-id"] = rid
            return response
        finally:
            _request_id_ctx.reset(token)


app.add_middleware(RequestIdMiddleware)

ALLOWED_ORIGINS = [o.strip() for o in os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"
).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin"],
    max_age=600,
)


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/heic", "image/heif"}

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    logger.warning("pillow-heif not installed; HEIC uploads will be rejected")
    ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png"}


class SubmissionCreate(BaseModel):
    image_url: str = Field(..., description="Where the uploaded invoice image is stored")
    extracted_data: Optional[Dict[str, Any]] = Field(default=None)


def _log_audit(cur, conn, user_id: Optional[str], action: str, subject_id: Optional[str]) -> None:
    """Insert one audit_log row for a state-changing manager action."""
    if is_sqlite_conn(conn):
        cur.execute(
            "INSERT INTO audit_log (id, user_id, action, subject_id) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, action, subject_id),
        )
    else:
        cur.execute(
            "INSERT INTO audit_log (user_id, action, subject_id) VALUES (%s, %s, %s)",
            (user_id, action, subject_id),
        )


def normalize_submission(row: Dict[str, Any]) -> Dict[str, Any]:
    if row is None:
        return row
    if row.get("id") is not None:
        row["id"] = str(row["id"])
    ed = row.get("extracted_data")
    if isinstance(ed, str):
        try:
            row["extracted_data"] = json.loads(ed) if ed else {}
        except Exception:
            row["extracted_data"] = {}
    elif ed is None:
        row["extracted_data"] = {}
    return row


def _to_float(val) -> Optional[float]:
    try:
        return float(val) if val not in (None, "", " ") else None
    except (ValueError, TypeError):
        return None


def _to_int(val) -> Optional[int]:
    try:
        return int(float(val)) if val not in (None, "", " ") else None
    except (ValueError, TypeError):
        return None


@app.on_event("startup")
def _warmup_ocr_models() -> None:
    """Load the TrOCR weights once at startup so the first upload does not
    have to wait for the model to load."""
    if os.getenv("SKIP_OCR_WARMUP") == "1":
        return
    try:
        from app.ocr.handwriting import _load_handwritten
        _load_handwritten()
        logger.info("TrOCR handwritten model pre-loaded at startup")
    except Exception:
        logger.exception("OCR warmup failed. Uploads will load the model on first use.")


@app.get("/health", tags=["System"])
def health():
    """Report the liveness of the API and which database is serving requests."""
    uptime_seconds = int((datetime.now(timezone.utc) - _STARTED_AT).total_seconds())
    try:
        from app.ocr.handwriting import _hw_model
        model_loaded = _hw_model is not None
    except Exception:
        model_loaded = False
    return {
        "status": "ok",
        "db": ACTIVE_DB,
        "uptime_seconds": uptime_seconds,
        "ocr_model_loaded": model_loaded,
    }


# Authentication: login, whoami, password change, recovery-code reset.

class LoginPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
    remember: bool = Field(default=False)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user: Dict[str, Any]


@app.post("/auth/login", response_model=LoginResponse, tags=["Auth"])
def login(payload: LoginPayload, request: Request):
    client_key = client_key_from_request(request)

    # Throttle brute-force attempts before the bcrypt verify (which is expensive).
    if is_locked_out(client_key):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again in a few minutes.",
        )

    user = lookup_user(payload.username.strip())
    # Always run a bcrypt verify, even when the user is absent, so the
    # response time does not leak username existence (OWASP ASVS V2.1.13).
    stored_hash = user["password_hash"] if user else None
    valid = constant_time_bcrypt_check(payload.password, stored_hash)

    if not (user and valid):
        register_failed_attempt(client_key)
        # Generic error to prevent username enumeration.
        raise HTTPException(status_code=401, detail="Invalid credentials")

    clear_failed_attempts(client_key)
    touch_last_login(str(user["id"]))
    token, expires = create_access_token(str(user["id"]), remember=payload.remember)

    return LoginResponse(
        access_token=token,
        expires_at=expires.isoformat(),
        user={
            "id": str(user["id"]),
            "username": user["username"],
            "role": user["role"],
        },
    )


@app.get("/auth/me", tags=["Auth"])
def whoami(current=Depends(require_manager)):
    user = lookup_user_by_id(current["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="Account no longer exists")
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "last_login_at": user.get("last_login_at"),
        "password_changed_at": user.get("password_changed_at"),
    }


@app.get("/auth/status", tags=["Auth"])
def auth_status():
    """Advertise whether a manager exists so the UI can steer onboarding vs
    sign-in. Deliberately exposes no usernames or timestamps."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM users")
        row = dict(cur.fetchone())
        cur.close()
        return {"has_manager": bool(row["c"])}
    finally:
        conn.close()


@app.get("/auth/password-rules", tags=["Auth"])
def password_rules():
    """Echo the policy checklist so UI and server share one source of truth."""
    return {"rules": evaluate_password_rules("")}


class ChangePasswordPayload(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=1, max_length=128)


@app.post("/auth/change-password", tags=["Auth"])
def change_password(payload: ChangePasswordPayload, current=Depends(require_manager)):
    user = lookup_user(None, user_id=current["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="Account no longer exists")
    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="New password must differ from the current one")

    ok, reason = validate_password_policy(payload.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    new_hash = hash_password(payload.new_password)
    recovery_code = generate_recovery_code()
    recovery_hash = hash_password(normalise_recovery_code(recovery_code))

    conn = get_connection()
    try:
        cur = conn.cursor()
        now_fn = "datetime('now')" if is_sqlite_conn(conn) else "NOW()"
        cur.execute(
            qmark(
                f"UPDATE users SET password_hash = %s, recovery_code_hash = %s, "
                f"password_changed_at = {now_fn} WHERE id = %s",
                conn,
            ),
            (new_hash, recovery_hash, str(user["id"])),
        )
        _invalidate_outstanding_reset_tokens(cur, conn, str(user["id"]))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return {"status": "password_changed", "recovery_code": recovery_code}


class ForgotPasswordPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    recovery_code: str = Field(..., min_length=1, max_length=64)
    new_password: str = Field(..., min_length=1, max_length=128)


@app.post("/auth/forgot-password", tags=["Auth"])
def forgot_password(payload: ForgotPasswordPayload, request: Request):
    client_key = client_key_from_request(request)
    if is_locked_out(client_key):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again in a few minutes.",
        )

    user = lookup_user(payload.username.strip())
    # constant_time_bcrypt_check keeps the timing indistinguishable between
    # existing and missing accounts (OWASP ASVS V2.1.13).
    stored_hash = user.get("recovery_code_hash") if user else None
    code_ok = constant_time_bcrypt_check(
        normalise_recovery_code(payload.recovery_code),
        stored_hash,
    )
    if not (user and code_ok):
        register_failed_attempt(client_key)
        raise HTTPException(status_code=401, detail="Invalid recovery code")

    ok, reason = validate_password_policy(payload.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    clear_failed_attempts(client_key)

    new_hash = hash_password(payload.new_password)
    recovery_code = generate_recovery_code()
    recovery_hash = hash_password(normalise_recovery_code(recovery_code))

    conn = get_connection()
    try:
        cur = conn.cursor()
        now_fn = "datetime('now')" if is_sqlite_conn(conn) else "NOW()"
        cur.execute(
            qmark(
                f"UPDATE users SET password_hash = %s, recovery_code_hash = %s, "
                f"password_changed_at = {now_fn} WHERE id = %s",
                conn,
            ),
            (new_hash, recovery_hash, str(user["id"])),
        )
        _invalidate_outstanding_reset_tokens(cur, conn, str(user["id"]))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return {"status": "password_reset", "recovery_code": recovery_code}


def lookup_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            qmark(
                "SELECT id, username, role, last_login_at, password_changed_at "
                "FROM users WHERE id = %s",
                conn,
            ),
            (user_id,),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        conn.close()


# Email-based password reset flow: issue a single-use token, email the link,
# exchange the token for a new password.

class RequestResetPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)


class ResetPasswordPayload(BaseModel):
    token: str = Field(..., min_length=16, max_length=128)
    new_password: str = Field(..., min_length=1, max_length=128)


def _frontend_url() -> str:
    url = (os.getenv("FRONTEND_URL") or "http://127.0.0.1:5173").rstrip("/")
    return url


def _invalidate_outstanding_reset_tokens(cur, conn, user_id: str) -> None:
    """Consume every unused token for a user so an in-flight email link
    cannot later be used to take over the account (OWASP ASVS V2.5.7)."""
    now_fn = "datetime('now')" if is_sqlite_conn(conn) else "NOW()"
    cur.execute(
        qmark(
            f"UPDATE password_reset_tokens SET used_at = {now_fn} "
            f"WHERE user_id = %s AND used_at IS NULL",
            conn,
        ),
        (user_id,),
    )


def _persist_reset_token(user_id: str, token: str) -> None:
    token_hash = hash_reset_token(token)
    expires = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)

    conn = get_connection()
    try:
        cur = conn.cursor()
        _invalidate_outstanding_reset_tokens(cur, conn, user_id)
        # Clean up any expired rows as part of the same transaction so the
        # table does not grow forever.
        if is_sqlite_conn(conn):
            cur.execute(
                "DELETE FROM password_reset_tokens WHERE expires_at < datetime('now')"
            )
        else:
            cur.execute("DELETE FROM password_reset_tokens WHERE expires_at < NOW()")
        # SQLite stores datetimes as text in the project's existing format.
        expires_value = (
            expires.strftime("%Y-%m-%d %H:%M:%S")
            if is_sqlite_conn(conn)
            else expires
        )
        cur.execute(
            qmark(
                "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
                "VALUES (%s, %s, %s)",
                conn,
            ),
            (user_id, token_hash, expires_value),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


@app.post("/auth/request-reset", tags=["Auth"])
def request_password_reset(payload: RequestResetPayload, request: Request):
    """Start the email reset flow. Always returns a generic acknowledgement
    to prevent username enumeration."""
    client_key = client_key_from_request(request)
    if is_locked_out(client_key):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Try again in a few minutes.",
        )

    user = lookup_user(payload.username.strip())
    if user and user.get("email"):
        token = generate_reset_token()
        _persist_reset_token(str(user["id"]), token)

        reset_url = f"{_frontend_url()}/?reset_token={token}"
        html, text = render_reset_email(
            username=user["username"],
            reset_url=reset_url,
            expires_minutes=RESET_TOKEN_TTL_MINUTES,
        )
        delivered = send_email(
            to=user["email"],
            subject="Reset your AGW Heating password",
            html=html,
            text=text,
        )
        if not delivered:
            # Surface the link to the operator console so a local demo can
            # proceed when outbound email is unavailable.
            logger.info("Reset link for %s: %s", user["username"], reset_url)
    else:
        # Equalise response timing with the real lookup/send path.
        time.sleep(0.2)

    return {
        "status": "reset_email_sent_if_account_exists",
        "expires_minutes": RESET_TOKEN_TTL_MINUTES,
    }


@app.post("/auth/reset-password", tags=["Auth"])
def reset_password(payload: ResetPasswordPayload, request: Request):
    """Exchange a valid reset token for a password change."""
    client_key = client_key_from_request(request)
    if is_locked_out(client_key):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again in a few minutes.",
        )

    token_hash = hash_reset_token(payload.token)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            qmark(
                "SELECT id, user_id, expires_at, used_at FROM password_reset_tokens "
                "WHERE token_hash = %s",
                conn,
            ),
            (token_hash,),
        )
        row = cur.fetchone()

        if not row:
            register_failed_attempt(client_key)
            raise HTTPException(status_code=400, detail="This reset link is invalid or has already been used.")
        row = dict(row)

        if row.get("used_at"):
            raise HTTPException(status_code=400, detail="This reset link has already been used.")

        expires_at = row["expires_at"]
        if isinstance(expires_at, str):
            expires_dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        else:
            expires_dt = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        if expires_dt <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="This reset link has expired. Request a new one.")

        ok, reason = validate_password_policy(payload.new_password)
        if not ok:
            raise HTTPException(status_code=400, detail=reason)

        clear_failed_attempts(client_key)

        new_hash = hash_password(payload.new_password)
        recovery_code = generate_recovery_code()
        recovery_hash = hash_password(normalise_recovery_code(recovery_code))

        now_fn = "datetime('now')" if is_sqlite_conn(conn) else "NOW()"
        cur.execute(
            qmark(
                f"UPDATE users SET password_hash = %s, recovery_code_hash = %s, "
                f"password_changed_at = {now_fn} WHERE id = %s",
                conn,
            ),
            (new_hash, recovery_hash, str(row["user_id"])),
        )
        _invalidate_outstanding_reset_tokens(cur, conn, str(row["user_id"]))

        conn.commit()
        cur.close()
    finally:
        conn.close()

    return {"status": "password_reset", "recovery_code": recovery_code}


# Submission endpoints: create, list, update, delete rows in the review queue.

@app.post("/submissions", tags=["Submissions"])
def create_submission(payload: SubmissionCreate, _user=Depends(require_manager)):
    conn = get_connection()
    try:
        cur = conn.cursor()
        extracted = json.dumps(payload.extracted_data or {})

        if is_sqlite_conn(conn):
            new_id = str(uuid.uuid4())
            cur.execute(
                qmark(
                    "INSERT INTO submissions (id, image_url, extracted_data, status) "
                    "VALUES (%s, %s, %s, %s) "
                    "RETURNING id, image_url, extracted_data, status, created_at",
                    conn,
                ),
                (new_id, payload.image_url, extracted, "pending_review"),
            )
        else:
            cur.execute(
                "INSERT INTO submissions (image_url, extracted_data, status) "
                "VALUES (%s, %s::jsonb, %s) "
                "RETURNING id, image_url, extracted_data, status, created_at",
                (payload.image_url, extracted, "pending_review"),
            )

        row = cur.fetchone()
        conn.commit()
        cur.close()
        return normalize_submission(dict(row)) if isinstance(row, dict) else row
    except psycopg2.Error:
        logger.exception("Submission insert failed")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error creating submission")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.get("/submissions/{submission_id}", tags=["Submissions"])
def get_submission(submission_id: str, _user=Depends(require_manager)):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            qmark(
                "SELECT id, image_url, extracted_data, status, created_at "
                "FROM submissions WHERE id = %s",
                conn,
            ),
            (submission_id,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="Submission not found")
        return normalize_submission(dict(row)) if isinstance(row, dict) else row
    except HTTPException:
        raise
    except psycopg2.Error:
        logger.exception("Submission read failed")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error reading submission")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.get("/submissions", response_model=List[SubmissionOut], tags=["Submissions"])
def list_submissions(status: str = "pending_review", _user=Depends(require_manager)):
    last_err: Optional[Exception] = None
    for attempt in range(3):
        conn = None
        try:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                qmark(
                    "SELECT id, image_url, extracted_data, status, created_at "
                    "FROM submissions WHERE status = %s ORDER BY created_at DESC",
                    conn,
                ),
                (status,),
            )
            rows = cur.fetchall()
            cur.close()
            return [normalize_submission(dict(r)) for r in rows]
        except psycopg2.OperationalError as e:
            last_err = e
            time.sleep(0.5 * (attempt + 1))
        except Exception:
            logger.exception("Unexpected error listing submissions")
            raise HTTPException(status_code=500, detail="Internal server error")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    logger.error("Database unreachable after 3 attempts: %s", last_err)
    raise HTTPException(
        status_code=503,
        detail="Database temporarily unreachable. Please retry in a moment.",
    )


@app.patch("/submissions/{submission_id}", tags=["Submissions"])
def update_submission(submission_id: str, payload: Dict[str, Any], _user=Depends(require_manager)):
    """Apply reviewer corrections to a pending submission."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            qmark("SELECT status FROM submissions WHERE id = %s", conn),
            (submission_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Submission not found")
        if dict(row)["status"] == "approved":
            raise HTTPException(status_code=400, detail="Cannot edit an approved submission")

        extracted = json.dumps(payload.get("extracted_data", {}))
        if is_sqlite_conn(conn):
            cur.execute(
                qmark("UPDATE submissions SET extracted_data = %s WHERE id = %s", conn),
                (extracted, submission_id),
            )
        else:
            cur.execute(
                "UPDATE submissions SET extracted_data = %s::jsonb WHERE id = %s",
                (extracted, submission_id),
            )

        conn.commit()
        cur.close()
        return {"updated": submission_id}
    except HTTPException:
        raise
    except psycopg2.Error:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.delete("/submissions/{submission_id}", tags=["Submissions"])
def delete_submission(submission_id: str, current=Depends(require_manager)):
    """Remove a pending submission from the review queue."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            qmark("SELECT status FROM submissions WHERE id = %s", conn),
            (submission_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Submission not found")
        if dict(row)["status"] == "approved":
            raise HTTPException(
                status_code=400,
                detail="Cannot delete an approved submission",
            )

        cur.execute(
            qmark("DELETE FROM submissions WHERE id = %s", conn),
            (submission_id,),
        )
        _log_audit(cur, conn, current.get("sub"), "submission.deleted", submission_id)
        conn.commit()
        cur.close()
        return {"deleted": submission_id}
    except HTTPException:
        raise
    except psycopg2.Error:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


# Approval pipeline: materialise a reviewed submission into the real
# invoice / line-item / product / stock-movement tables atomically.

def _insert_invoice_header(cur, conn, submission_id: str, structured: Dict[str, Any]) -> str:
    """Create the invoice row and return its id."""
    customer = structured.get("customer") or {}
    values = (
        submission_id,
        structured.get("invoice_number") or None,
        structured.get("invoice_date") or None,
        customer.get("name") or None,
        customer.get("phone") or None,
        _to_float(structured.get("net_total")),
        _to_float(structured.get("vat")),
        _to_float(structured.get("amount_due")),
    )

    if is_sqlite_conn(conn):
        invoice_id = str(uuid.uuid4())
        cur.execute(
            qmark(
                "INSERT INTO invoices "
                "(id, submission_id, invoice_number, invoice_date, "
                " customer_name, customer_phone, net_total, vat, amount_due) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                conn,
            ),
            (invoice_id, *values),
        )
        return invoice_id

    cur.execute(
        "INSERT INTO invoices "
        "(submission_id, invoice_number, invoice_date, "
        " customer_name, customer_phone, net_total, vat, amount_due) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        values,
    )
    return str(cur.fetchone()["id"])


def _upsert_product(cur, conn, name: str) -> str:
    """Insert a product by name and return its id using an atomic upsert.

    On Postgres the ON CONFLICT RETURNING handles the race in a single
    statement. On SQLite the INSERT OR IGNORE plus SELECT runs inside the
    transaction started by approve_submission, which already holds the
    write lock, so no other connection can slip in between the two.
    """
    if is_sqlite_conn(conn):
        product_id = str(uuid.uuid4())
        cur.execute(
            "INSERT OR IGNORE INTO products (id, name, current_stock) VALUES (?, ?, 0)",
            (product_id, name),
        )
        cur.execute("SELECT id FROM products WHERE name = ?", (name,))
        return str(cur.fetchone()["id"])

    cur.execute(
        "INSERT INTO products (name, current_stock) VALUES (%s, 0) "
        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
        "RETURNING id",
        (name,),
    )
    return str(cur.fetchone()["id"])


def _insert_line_item_with_product(
    cur,
    conn,
    submission_id: str,
    invoice_id: str,
    item: Dict[str, Any],
) -> Optional[str]:
    """Insert a single invoice_items row. Returns the product_id when the
    item has a usable description, otherwise ``None``."""
    desc = (item.get("description") or "").strip() or None
    qty = _to_int(item.get("quantity"))
    unit_price = _to_float(item.get("unit_price"))
    amount = _to_float(item.get("amount"))

    if is_sqlite_conn(conn):
        item_id = str(uuid.uuid4())
        cur.execute(
            qmark(
                "INSERT INTO invoice_items "
                "(id, submission_id, invoice_id, description, quantity, unit_price, amount) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                conn,
            ),
            (item_id, submission_id, invoice_id, desc, qty, unit_price, amount),
        )
    else:
        cur.execute(
            "INSERT INTO invoice_items "
            "(submission_id, invoice_id, description, quantity, unit_price, amount) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (submission_id, invoice_id, desc, qty, unit_price, amount),
        )

    if not desc:
        return None
    return _upsert_product(cur, conn, desc)


def _record_stock_movement(
    cur,
    conn,
    product_id: str,
    submission_id: str,
    quantity_change: int,
) -> None:
    """Log a stock_movements row and adjust the running product stock."""
    if is_sqlite_conn(conn):
        cur.execute(
            qmark(
                "INSERT INTO stock_movements "
                "(id, product_id, submission_id, quantity_change) "
                "VALUES (%s,%s,%s,%s)",
                conn,
            ),
            (str(uuid.uuid4()), product_id, submission_id, quantity_change),
        )
    else:
        cur.execute(
            "INSERT INTO stock_movements "
            "(product_id, submission_id, quantity_change) "
            "VALUES (%s,%s,%s)",
            (product_id, submission_id, quantity_change),
        )

    if quantity_change:
        cur.execute(
            qmark(
                "UPDATE products SET current_stock = current_stock + %s WHERE id = %s",
                conn,
            ),
            (quantity_change, product_id),
        )


@app.post("/submissions/{submission_id}/approve", tags=["Submissions"])
def approve_submission(submission_id: str, current=Depends(require_manager)):
    """Approve a reviewed submission and materialise it into the invoice DB."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        # FOR UPDATE on Postgres serialises concurrent approvals of the same
        # submission and prevents a duplicate invoice header; qmark strips it
        # on SQLite where the write-lock is already exclusive per connection.
        cur.execute(
            qmark(
                "SELECT status, extracted_data FROM submissions WHERE id = %s FOR UPDATE",
                conn,
            ),
            (submission_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Submission not found")

        row = dict(row)
        if row["status"] == "approved":
            raise HTTPException(status_code=400, detail="Submission already approved")

        ed = row["extracted_data"]
        if isinstance(ed, str):
            ed = json.loads(ed) if ed else {}

        structured = ed.get("structured", {})

        # An invoice with no line items would leave an orphan header; force
        # the reviewer to add at least one row first.
        if not structured.get("line_items"):
            raise HTTPException(
                status_code=400,
                detail="Cannot approve: no line items detected. Add at least one item before approving.",
            )

        invoice_id = _insert_invoice_header(cur, conn, submission_id, structured)

        for item in structured.get("line_items", []):
            product_id = _insert_line_item_with_product(
                cur, conn, submission_id, invoice_id, item,
            )
            if product_id is None:
                continue
            _record_stock_movement(
                cur, conn, product_id, submission_id, _to_int(item.get("quantity")) or 0,
            )

        cur.execute(
            qmark("UPDATE submissions SET status = 'approved' WHERE id = %s", conn),
            (submission_id,),
        )

        _log_audit(cur, conn, current.get("sub"), "submission.approved", submission_id)

        conn.commit()
        return {"status": "approved", "submission_id": submission_id, "invoice_id": invoice_id}

    except HTTPException:
        conn.rollback()
        raise
    except psycopg2.Error:
        conn.rollback()
        logger.exception("Approval transaction failed")
        raise HTTPException(status_code=500, detail="Database error during approval")
    except Exception:
        conn.rollback()
        logger.exception("Unexpected error during approval")
        raise HTTPException(status_code=500, detail="Internal server error during approval")
    finally:
        cur.close()
        conn.close()


# Invoice and product read endpoints for the dashboard pages.

# Allow-list of sortable columns so a bad ?sort= value cannot turn into
# SQL injection even though the column is interpolated into the statement.
_INVOICE_SORT_COLUMNS = {"created_at", "invoice_date", "amount_due", "invoice_number"}


@app.get("/invoices", response_model=List[InvoiceOut], tags=["Invoices"])
def list_invoices(
    limit: int = 100,
    offset: int = 0,
    sort: str = "-created_at",
    _user=Depends(require_manager),
):
    # Clamp to sensible bounds so a malformed request cannot exhaust memory.
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    direction = "DESC"
    column = sort
    if sort.startswith("-"):
        column = sort[1:]
    elif sort.startswith("+"):
        column = sort[1:]
        direction = "ASC"
    if column not in _INVOICE_SORT_COLUMNS:
        column = "created_at"
        direction = "DESC"

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            qmark(
                "SELECT id, submission_id, invoice_number, invoice_date, "
                "       customer_name, customer_phone, net_total, vat, amount_due, created_at "
                f"FROM invoices ORDER BY {column} {direction} LIMIT %s OFFSET %s",
                conn,
            ),
            (limit, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            r["id"] = str(r["id"])
            r["submission_id"] = str(r["submission_id"])
            r["items"] = []
        return rows
    except psycopg2.Error:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.get("/invoices/{invoice_id}", response_model=InvoiceOut, tags=["Invoices"])
def get_invoice(invoice_id: str, _user=Depends(require_manager)):
    conn = get_connection()
    try:
        cur = conn.cursor()

        # invoice_items.ORDER BY rowid works on SQLite only; use a column name
        # that exists on both engines.
        items_order = "rowid" if is_sqlite_conn(conn) else "id"

        cur.execute(
            qmark(
                "SELECT id, submission_id, invoice_number, invoice_date, "
                "       customer_name, customer_phone, net_total, vat, amount_due, created_at "
                "FROM invoices WHERE id = %s",
                conn,
            ),
            (invoice_id,),
        )
        inv = cur.fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")
        inv = dict(inv)
        inv["id"] = str(inv["id"])
        inv["submission_id"] = str(inv["submission_id"])

        cur.execute(
            qmark(
                "SELECT id, submission_id, invoice_id, description, "
                "       quantity, unit_price, amount, confidence "
                f"FROM invoice_items WHERE invoice_id = %s ORDER BY {items_order}",
                conn,
            ),
            (invoice_id,),
        )
        inv["items"] = [dict(r) for r in cur.fetchall()]
        cur.close()
        return inv
    except HTTPException:
        raise
    except psycopg2.Error:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.delete("/products/{product_id}", tags=["Products"])
def delete_product(product_id: str, current=Depends(require_manager)):
    """Delete a product and its associated stock movements."""
    conn = get_connection()
    try:
        cur = conn.cursor()

        cur.execute(
            qmark("SELECT id FROM products WHERE id = %s", conn),
            (product_id,),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Product not found")

        cur.execute(
            qmark("DELETE FROM stock_movements WHERE product_id = %s", conn),
            (product_id,),
        )
        cur.execute(
            qmark("DELETE FROM products WHERE id = %s", conn),
            (product_id,),
        )
        _log_audit(cur, conn, current.get("sub"), "product.deleted", product_id)
        conn.commit()
        cur.close()
        return {"deleted": product_id}
    except HTTPException:
        raise
    except psycopg2.Error:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.get("/invoices/count", tags=["Invoices"])
def count_invoices(_user=Depends(require_manager)):
    """Return the total count of approved invoices, used alongside /invoices
    paging on the dashboard."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM invoices")
        total = dict(cur.fetchone())["c"]
        cur.close()
        return {"total": total}
    finally:
        conn.close()


@app.get("/audit-log", tags=["System"])
def list_audit_log(
    limit: int = 100,
    offset: int = 0,
    _user=Depends(require_manager),
):
    """List audit-log entries newest first. Manager-only."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            qmark(
                "SELECT id, user_id, action, subject_id, created_at "
                "FROM audit_log ORDER BY created_at DESC LIMIT %s OFFSET %s",
                conn,
            ),
            (limit, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            r["id"] = str(r["id"])
            if r.get("user_id"):
                r["user_id"] = str(r["user_id"])
        return rows
    finally:
        conn.close()


@app.get("/products", response_model=List[ProductOut], tags=["Products"])
def list_products(
    limit: int = 200,
    offset: int = 0,
    _user=Depends(require_manager),
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            qmark(
                "SELECT id, name, current_stock FROM products "
                "ORDER BY name LIMIT %s OFFSET %s",
                conn,
            ),
            (limit, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            r["id"] = str(r["id"])
        return rows
    except psycopg2.Error:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


# Analytics endpoints: feed the charts and KPIs on the dashboard page.

@app.get("/analytics/summary", tags=["Analytics"])
def analytics_summary(_user=Depends(require_manager)):
    conn = get_connection()
    try:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) as cnt FROM invoices")
        total_invoices = dict(cur.fetchone())["cnt"]

        cur.execute("SELECT COALESCE(SUM(amount_due), 0) as total FROM invoices")
        total_spend = float(dict(cur.fetchone())["total"] or 0)

        cur.execute("SELECT COUNT(*) as cnt FROM products")
        total_products = dict(cur.fetchone())["cnt"]

        cur.execute(
            qmark(
                "SELECT COUNT(*) as cnt FROM submissions WHERE status = %s",
                conn,
            ),
            ("pending_review",),
        )
        pending = dict(cur.fetchone())["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM invoice_items")
        total_items = dict(cur.fetchone())["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM submissions")
        total_processed = dict(cur.fetchone())["cnt"]

        avg_value = round(total_spend / total_invoices, 2) if total_invoices else 0

        cur.close()
        return {
            "total_invoices": total_invoices,
            "total_spend": total_spend,
            "avg_invoice_value": avg_value,
            "total_products": total_products,
            "total_line_items": total_items,
            "pending_submissions": pending,
            "total_processed": total_processed,
        }
    except psycopg2.Error:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.get("/analytics/monthly-spend", tags=["Analytics"])
def analytics_monthly_spend(_user=Depends(require_manager)):
    conn = get_connection()
    try:
        cur = conn.cursor()

        if is_sqlite_conn(conn):
            cur.execute(
                "SELECT strftime('%Y-%m', created_at) as month, "
                "       COUNT(*) as invoice_count, "
                "       COALESCE(SUM(amount_due), 0) as total_spend "
                "FROM invoices GROUP BY month ORDER BY month"
            )
        else:
            cur.execute(
                "SELECT to_char(created_at, 'YYYY-MM') as month, "
                "       COUNT(*) as invoice_count, "
                "       COALESCE(SUM(amount_due), 0) as total_spend "
                "FROM invoices GROUP BY month ORDER BY month"
            )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            r["total_spend"] = float(r["total_spend"] or 0)
        return rows
    except psycopg2.Error:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.get("/analytics/top-products", tags=["Analytics"])
def analytics_top_products(_user=Depends(require_manager)):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT description, "
            "       COUNT(*) as frequency, "
            "       COALESCE(SUM(amount), 0) as total_spend, "
            "       COALESCE(AVG(amount), 0) as avg_price "
            "FROM invoice_items "
            "WHERE description IS NOT NULL AND description != '' "
            "GROUP BY description "
            "ORDER BY total_spend DESC "
            "LIMIT 15"
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            r["total_spend"] = float(r["total_spend"] or 0)
            r["avg_price"] = round(float(r["avg_price"] or 0), 2)
        return rows
    except psycopg2.Error:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.get("/analytics/stock-forecast", tags=["Analytics"])
def analytics_stock_forecast(_user=Depends(require_manager)):
    conn = get_connection()
    try:
        cur = conn.cursor()

        if is_sqlite_conn(conn):
            cur.execute(
                "SELECT p.name, p.current_stock, "
                "       sm.quantity_change, "
                "       strftime('%Y-%m-%d', sm.created_at) as date "
                "FROM stock_movements sm "
                "JOIN products p ON p.id = sm.product_id "
                "ORDER BY sm.created_at"
            )
        else:
            cur.execute(
                "SELECT p.name, p.current_stock, "
                "       sm.quantity_change, "
                "       to_char(sm.created_at, 'YYYY-MM-DD') as date "
                "FROM stock_movements sm "
                "JOIN products p ON p.id = sm.product_id "
                "ORDER BY sm.created_at"
            )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    except psycopg2.Error:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.get("/analytics/model-performance", tags=["Analytics"])
def analytics_model_performance(_user=Depends(require_manager)):
    """Training stats and evaluation results for the TrOCR fine-tuning pipeline."""
    data_root = Path(__file__).resolve().parents[2] / "data"
    ft_dir = data_root / "trocr-finetuned"

    result = {
        "has_finetuned_model": (ft_dir / "final").exists(),
        "training": None,
        "evaluation": None,
        "dataset": None,
    }

    stats_path = ft_dir / "training_stats.json"
    if stats_path.exists():
        try:
            result["training"] = json.loads(stats_path.read_text())
        except Exception:
            pass

    eval_path = ft_dir / "evaluation_results.json"
    if eval_path.exists():
        try:
            result["evaluation"] = json.loads(eval_path.read_text())
        except Exception:
            pass

    crops_dir = data_root / "crops"
    if crops_dir.exists():
        total_crops = 0
        labelled_crops = 0
        receipt_count = 0
        for manifest in crops_dir.glob("*/manifest.json"):
            receipt_count += 1
            parent = manifest.parent
            for txt in parent.glob("*_description.txt"):
                total_crops += 1
                content = txt.read_text(encoding="utf-8").strip()
                if content:
                    labelled_crops += 1
        result["dataset"] = {
            "receipts_processed": receipt_count,
            "total_crops": total_crops,
            "labelled_crops": labelled_crops,
            "label_progress": round(labelled_crops / max(total_crops, 1) * 100, 1),
        }

    return result


@app.get("/analytics/ocr-confidence", tags=["Analytics"])
def analytics_ocr_confidence(_user=Depends(require_manager)):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, extracted_data, status, created_at FROM submissions "
            "ORDER BY created_at DESC LIMIT 50"
        )
        rows = [normalize_submission(dict(r)) for r in cur.fetchall()]
        cur.close()

        metrics = []
        for row in rows:
            ed = row.get("extracted_data") or {}
            structured = ed.get("structured", {})
            items = structured.get("line_items", [])
            fields_present = sum([
                bool(structured.get("invoice_number")),
                bool(structured.get("invoice_date")),
                bool(structured.get("customer", {}).get("name")),
                bool(structured.get("amount_due")),
            ])
            items_with_amount = sum(1 for i in items if i.get("amount"))
            items_with_desc = sum(1 for i in items if i.get("description"))
            total_items = len(items)

            score = round(
                (fields_present / 4 * 40)
                + (items_with_amount / max(total_items, 1) * 30)
                + (items_with_desc / max(total_items, 1) * 30)
            ) if total_items else round(fields_present / 4 * 100)

            # Skip old approved submissions with no usable OCR data.
            if score == 0 and total_items == 0:
                continue

            metrics.append({
                "submission_id": row["id"],
                "status": row["status"],
                "created_at": str(row.get("created_at", "")),
                "header_completeness": round(fields_present / 4 * 100),
                "items_detected": total_items,
                "items_with_amount": items_with_amount,
                "items_with_description": items_with_desc,
                "extraction_score": score,
            })
        return metrics
    except psycopg2.Error:
        logger.exception("Database error")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


# Upload endpoint: receive an image, run the OCR pipeline,
# write a pending_review submission row.

# PIL reads the first few bytes of the file to detect the actual format.
# Comparing it against the client-declared content-type catches uploads
# that have been renamed to look like an image but are not one.
_PIL_FORMAT_TO_MIME = {
    "JPEG": {"image/jpeg"},
    "PNG": {"image/png"},
    "HEIF": {"image/heic", "image/heif"},
    "HEIC": {"image/heic", "image/heif"},
}


def _validate_upload(file: UploadFile, image_bytes: bytes) -> None:
    """Enforce size, declared content-type, and header/magic-byte checks."""
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    declared = (file.content_type or "").lower()
    if declared not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported content type: {declared or 'unknown'}",
        )

    try:
        probe = Image.open(io.BytesIO(image_bytes))
        detected_format = (probe.format or "").upper()
        probe.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image")

    expected_mimes = _PIL_FORMAT_TO_MIME.get(detected_format)
    if expected_mimes and declared not in expected_mimes:
        # Client says one thing, file bytes say another. Reject it.
        raise HTTPException(
            status_code=415,
            detail="File content does not match the declared type",
        )


@app.post("/submissions/upload", response_model=SubmissionOut, tags=["Submissions"])
async def upload_submission(file: UploadFile = File(...), _user=Depends(require_manager)):
    """Upload an invoice image, run OCR, store as pending_review."""
    from app.ocr.receipt_pipeline import process_receipt

    image_bytes = await file.read()
    _validate_upload(file, image_bytes)

    try:
        structured = process_receipt(image_bytes)
    except Exception:
        logger.exception("OCR pipeline failed")
        raise HTTPException(status_code=500, detail="OCR pipeline failed")

    raw_text = structured.get("raw_text", "")
    extracted_data = {
        "ocr": {
            "raw_text": raw_text,
            "engine": "trocr-large-handwritten+tesseract",
            "scope": "full_document",
        },
        "structured": structured,
    }
    extracted_json = json.dumps(extracted_data)

    conn = get_connection()
    try:
        cur = conn.cursor()

        if is_sqlite_conn(conn):
            new_id = str(uuid.uuid4())
            cur.execute(
                qmark(
                    "INSERT INTO submissions (id, image_url, extracted_data, status) "
                    "VALUES (%s, %s, %s, %s) "
                    "RETURNING id, image_url, extracted_data, status, created_at",
                    conn,
                ),
                (new_id, "uploaded_file", extracted_json, "pending_review"),
            )
        else:
            cur.execute(
                "INSERT INTO submissions (image_url, extracted_data, status) "
                "VALUES (%s, %s::jsonb, %s) "
                "RETURNING id, image_url, extracted_data, status, created_at",
                ("uploaded_file", extracted_json, "pending_review"),
            )

        row = cur.fetchone()
        conn.commit()
        cur.close()
        return normalize_submission(dict(row)) if isinstance(row, dict) else row

    except HTTPException:
        raise
    except psycopg2.Error:
        logger.exception("Upload database insert failed")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception:
        logger.exception("Unexpected error saving upload")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()
