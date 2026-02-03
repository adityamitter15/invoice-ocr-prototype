from app.schemas import SubmissionOut, ApproveSubmissionIn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, List
from app.database import get_connection
import json
from fastapi import UploadFile, File
from app.ocr.handwriting import handwriting_ocr


app = FastAPI(title="Invoice OCR Prototype API")

# CORS: allow the Vite dev server to call the API during local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
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

        return dict(row) if isinstance(row, dict) else row

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

        return dict(row) if isinstance(row, dict) else row

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
    


# @app.post("/ocr/handwriting")
# async def ocr_handwriting(file: UploadFile = File(...)):
#     data = await file.read()
#     text = handwriting_ocr(data)
#     return {"text": text}

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

        # 3) Store submission (image_url is placeholder for now)
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO submissions (image_url, extracted_data, status)
            VALUES (%s, %s::jsonb, %s)
            RETURNING id, image_url, extracted_data, status, created_at;
            """,
            ("uploaded_file", json.dumps(extracted_data), "pending_review"),
        )

        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        return dict(row) if isinstance(row, dict) else row

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")