from app.schemas import SubmissionOut, ApproveSubmissionIn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, List
from app.database import get_connection
import json

app = FastAPI(title="Invoice OCR Prototype API")


class SubmissionCreate(BaseModel):
    image_url: str = Field(..., description="Where the uploaded invoice image is stored (temp string for now)")
    extracted_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="OCR + extraction output (JSON). Can be partial in prototype."
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/submissions")
def create_submission(payload: SubmissionCreate):
    # Default to pending_review for HITL workflow
    status = "pending_review"

    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO submissions (image_url, extracted_data, status)
            VALUES (%s, %s::jsonb, %s)
            RETURNING id, image_url, extracted_data, status, created_at;
            """,
            (payload.image_url, json.dumps(payload.extracted_data or {}), status),
        )

        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return row

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database insert failed: {str(e)}")


@app.get("/submissions/{submission_id}")
def get_submission(submission_id: str):
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, image_url, extracted_data, status, created_at
            FROM submissions
            WHERE id = %s
            """,
            (submission_id,),
        )

        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Submission not found")

        return row

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")

    
@app.get("/submissions", response_model=List[SubmissionOut])
def list_submissions(status: str = "pending_review"):
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, image_url, extracted_data, status, created_at
            FROM submissions
            WHERE status = %s
            ORDER BY created_at DESC
            """,
            (status,),
        )

        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Ensure rows are plain JSON-serializable dicts (avoids FastAPI/Pydantic 500s)
        return [dict(r) for r in rows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"List failed: {str(e)}")
    
@app.post("/submissions/{submission_id}/approve")
def approve_submission(submission_id: str, payload: ApproveSubmissionIn):
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Start transaction
        cur.execute(
            """
            SELECT status
            FROM submissions
            WHERE id = %s
            FOR UPDATE
            """,
            (submission_id,)
        )

        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Submission not found")

        # RealDictCursor returns dict-like rows; default cursor may return tuples
        current_status = row["status"] if isinstance(row, dict) else row[0]
        if current_status == "approved":
            raise HTTPException(status_code=400, detail="Submission already approved")

        # Insert invoice items
        for item in payload.items:
            cur.execute(
                """
                INSERT INTO invoice_items
                (submission_id, description, quantity, amount, confidence)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    submission_id,
                    item.description,
                    item.quantity,
                    item.amount,
                    item.confidence,
                )
            )

        # Mark submission as approved
        cur.execute(
            """
            UPDATE submissions
            SET status = 'approved'
            WHERE id = %s
            """,
            (submission_id,)
        )

        conn.commit()
        cur.close()
        conn.close()

        return {"status": "approved", "submission_id": submission_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))