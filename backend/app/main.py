from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
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