import uuid
import json
import time
from typing import Any, Dict, Optional, List

import psycopg2
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.schemas import SubmissionOut, ApproveSubmissionIn
from app.database import get_connection, ACTIVE_DB, qmark, is_sqlite_conn
from app.ocr.handwriting import handwriting_ocr


app = FastAPI(title="Invoice OCR Prototype API")

# CORS: allow the Vite dev server to call the API during local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # Optional: if you use Vite preview (`npm run preview`) it can run on 4173
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SubmissionCreate(BaseModel):
    image_url: str = Field(..., description="Where the uploaded invoice image is stored (temp string for now)")
    extracted_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="OCR + extraction output (JSON). Can be partial in prototype."
    )


def normalize_submission(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure API responses match SubmissionOut for BOTH Postgres + SQLite.
    - SQLite stores extracted_data as TEXT -> parse JSON into dict
    - Ensure id is a string
    """
    if row is None:
        return row

    # id always string
    if row.get("id") is not None:
        row["id"] = str(row["id"])

    # extracted_data should be dict
    ed = row.get("extracted_data")
    if isinstance(ed, str):
        try:
            row["extracted_data"] = json.loads(ed) if ed else {}
        except Exception:
            row["extracted_data"] = {}
    elif ed is None:
        row["extracted_data"] = {}

    return row


@app.get("/health")
def health():
    return {"status": "ok", "db": ACTIVE_DB}


@app.post("/submissions")
def create_submission(payload: SubmissionCreate):
    status = "pending_review"

    try:
        conn = get_connection()
        cur = conn.cursor()

        sql_pg = """
        INSERT INTO submissions (image_url, extracted_data, status)
        VALUES (%s, %s::jsonb, %s)
        RETURNING id, image_url, extracted_data, status, created_at;
        """

        sql_sqlite = """
        INSERT INTO submissions (id, image_url, extracted_data, status)
        VALUES (?, ?, ?, ?)
        RETURNING id, image_url, extracted_data, status, created_at;
        """

        if is_sqlite_conn(conn):
            new_id = str(uuid.uuid4())
            cur.execute(
                sql_sqlite,
                (new_id, payload.image_url, json.dumps(payload.extracted_data or {}), status),
            )
        else:
            cur.execute(
                sql_pg,
                (payload.image_url, json.dumps(payload.extracted_data or {}), status),
            )

        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return normalize_submission(dict(row)) if isinstance(row, dict) else row

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database insert failed: {str(e)}")


@app.get("/submissions/{submission_id}")
def get_submission(submission_id: str):
    try:
        conn = get_connection()
        cur = conn.cursor()

        sql_pg = """
        SELECT id, image_url, extracted_data, status, created_at
        FROM submissions
        WHERE id = %s
        """

        sql_sqlite = """
        SELECT id, image_url, extracted_data, status, created_at
        FROM submissions
        WHERE id = ?
        """

        cur.execute(sql_sqlite if is_sqlite_conn(conn) else sql_pg, (submission_id,))
        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Submission not found")

        return normalize_submission(dict(row)) if isinstance(row, dict) else row

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


@app.get("/submissions", response_model=List[SubmissionOut])
def list_submissions(status: str = "pending_review"):
    """
    List submissions by status.

    Supabase pooler can intermittently time out. For prototype robustness we:
    - retry a few times with short backoff
    - return 503 if DB is temporarily unreachable (instead of breaking the UI)
    """
    last_err: Optional[Exception] = None

    for attempt in range(3):
        try:
            conn = get_connection()
            cur = conn.cursor()

            sql_pg = """
            SELECT id, image_url, extracted_data, status, created_at
            FROM submissions
            WHERE status = %s
            ORDER BY created_at DESC
            """

            sql_sqlite = """
            SELECT id, image_url, extracted_data, status, created_at
            FROM submissions
            WHERE status = ?
            ORDER BY created_at DESC
            """

            cur.execute(sql_sqlite if is_sqlite_conn(conn) else sql_pg, (status,))
            rows = cur.fetchall()

            cur.close()
            conn.close()

            return [normalize_submission(dict(r)) for r in rows]

        except psycopg2.OperationalError as e:
            last_err = e
            time.sleep(0.5 * (attempt + 1))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"List failed: {str(e)}")

    raise HTTPException(
        status_code=503,
        detail=(
            "Database temporarily unreachable (Supabase pooler timeout). "
            f"Please retry. Last error: {str(last_err)}"
        ),
    )


@app.post("/submissions/{submission_id}/approve")
def approve_submission(submission_id: str, payload: ApproveSubmissionIn):
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Locking: Postgres supports FOR UPDATE; SQLite doesn't.
        sql_pg = """
        SELECT status
        FROM submissions
        WHERE id = %s
        FOR UPDATE
        """
        sql_sqlite = """
        SELECT status
        FROM submissions
        WHERE id = ?
        """
        cur.execute(sql_sqlite if is_sqlite_conn(conn) else sql_pg, (submission_id,))

        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Submission not found")

        current_status = row["status"] if isinstance(row, dict) else row[0]
        if current_status == "approved":
            raise HTTPException(status_code=400, detail="Submission already approved")

        # Insert invoice items
        sql_item_pg = """
        INSERT INTO invoice_items
        (submission_id, description, quantity, amount, confidence)
        VALUES (%s, %s, %s, %s, %s)
        """

        sql_item_sqlite = """
        INSERT INTO invoice_items
        (id, submission_id, description, quantity, amount, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """

        for item in payload.items:
            if is_sqlite_conn(conn):
                item_id = str(uuid.uuid4())
                cur.execute(
                    sql_item_sqlite,
                    (
                        item_id,
                        submission_id,
                        item.description,
                        item.quantity,
                        item.amount,
                        item.confidence,
                    ),
                )
            else:
                cur.execute(
                    sql_item_pg,
                    (
                        submission_id,
                        item.description,
                        item.quantity,
                        item.amount,
                        item.confidence,
                    ),
                )

        # Mark submission as approved
        sql_upd_pg = """
        UPDATE submissions
        SET status = 'approved'
        WHERE id = %s
        """
        sql_upd_sqlite = """
        UPDATE submissions
        SET status = 'approved'
        WHERE id = ?
        """
        cur.execute(sql_upd_sqlite if is_sqlite_conn(conn) else sql_upd_pg, (submission_id,))

        conn.commit()
        cur.close()
        conn.close()

        return {"status": "approved", "submission_id": submission_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/submissions/upload", response_model=SubmissionOut)
async def upload_submission(file: UploadFile = File(...)):
    """
    Upload an invoice image (prototype: key fields handwritten),
    run handwriting OCR, store results in extracted_data, status=pending_review.
    """
    try:
        image_bytes = await file.read()

        # 1) OCR (handwriting)
        raw_text = handwriting_ocr(image_bytes)

        # 2) Build extracted_data payload (prototype-friendly + traceable)
        extracted_data = {
            "ocr": {
                "raw_text": raw_text,
                "engine": "microsoft/trocr-base-handwritten",
                "scope": "key_fields",
            }
        }

        conn = get_connection()
        cur = conn.cursor()

        sql_pg = """
        INSERT INTO submissions (image_url, extracted_data, status)
        VALUES (%s, %s::jsonb, %s)
        RETURNING id, image_url, extracted_data, status, created_at;
        """

        sql_sqlite = """
        INSERT INTO submissions (id, image_url, extracted_data, status)
        VALUES (?, ?, ?, ?)
        RETURNING id, image_url, extracted_data, status, created_at;
        """

        if is_sqlite_conn(conn):
            new_id = str(uuid.uuid4())
            cur.execute(
                sql_sqlite,
                (new_id, "uploaded_file", json.dumps(extracted_data), "pending_review"),
            )
        else:
            cur.execute(
                sql_pg,
                ("uploaded_file", json.dumps(extracted_data), "pending_review"),
            )

        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return normalize_submission(dict(row)) if isinstance(row, dict) else row

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")