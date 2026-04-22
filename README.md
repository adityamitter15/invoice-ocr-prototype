# Handwritten Invoice OCR with Human-in-the-Loop Review

My BSc Computer Science final year project (University of Westminster, 2025/26).

The system digitises handwritten supplier invoices for a real wholesale business. Every invoice goes through a multi-engine OCR pipeline (TrOCR for cursive, EasyOCR for numerals, Tesseract for printed headers), then lands in a review queue where a manager corrects any errors and approves the record. Corrections feed a fine-tuning loop so the model improves with use.

Mean character error rate on 2,169 evaluation crops: **4.34%**. Exact-match on 97.7% of crops.

## Requirements

- Python 3.9+
- Node 18+
- Tesseract (`brew install tesseract` on macOS)
- ~3 GB free disk for the TrOCR model weights (downloaded on first run)

## Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in secrets
uvicorn app.main:app --reload
```

Runs on <http://127.0.0.1:8000>. OpenAPI docs at `/docs`.

First call to the OCR pipeline downloads the `microsoft/trocr-base-handwritten` checkpoint (~1.4 GB) into the Hugging Face cache.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs on <http://localhost:5173>. The login page appears first; seed credentials are set via the seed script (see below).

## Database

The backend probes Supabase PostgreSQL on startup with a 5-second wall-clock timeout. If Postgres is unreachable it falls back to `backend/local.db` (SQLite) for the rest of the session. Same schema works on both — see `backend/db/schema_sqlite.sql` and `db/schema.sql`.

To reset the local SQLite database:

```bash
cd backend
rm -f local.db
sqlite3 local.db < db/schema_sqlite.sql
```

## Creating a manager account

```bash
cd backend
python scripts/seed_manager.py   # prompts for username + password
```

This prints a one-time 16-character recovery code. Write it down — it only appears once and is used to reset the password without email.

## Demo flow

1. Start the backend and frontend.
2. Log in as the manager.
3. Drag a JPEG of a handwritten invoice onto the Upload tab.
4. Wait 15–25 seconds for the pipeline to run.
5. Open the submission from the Review Queue.
6. Correct any misread fields.
7. Click Approve. The invoice lands in the Invoices tab and the products/stock tables are updated atomically.

## Running the evaluation

```bash
cd backend
python scripts/evaluate_pipeline.py
```

This prints CER, WER and exact-match accuracy on the held-out invoice crops and writes `training_stats.json` for the analytics dashboard.

## Fine-tuning

```bash
cd backend
python scripts/build_dataset.py
python scripts/finetune_trocr.py --epochs 15 --batch-size 8
```

Checkpoints land in `backend/runs/<timestamp>/`. The OCR pipeline picks up the newest checkpoint automatically on next startup; if it's unavailable it falls back to the base model.

## Environment variables

See `backend/.env.example`. Key ones:

- `DATABASE_URL` — Postgres connection string for Supabase (optional; fallback to SQLite otherwise)
- `JWT_SECRET` — 64-byte random string
- `BCRYPT_COST` — defaults to 12
- `RESEND_API_KEY` — for password reset emails (optional)
- `ALLOWED_ORIGINS` — comma-separated CORS allowlist, defaults to the Vite dev URL
- `VITE_API_BASE_URL` — frontend only, points at the backend base URL

## Troubleshooting

**Backend fails with "Could not connect to Postgres"** — check `DATABASE_URL` or just leave it blank. The system will fall back to SQLite automatically.

**Upload returns 413** — the file is larger than 10 MB. Reduce resolution or crop.

**OCR takes 30+ seconds on the first invoice** — the TrOCR checkpoint is being downloaded from Hugging Face. Subsequent invoices run in 15–25 seconds on Apple M3.

**Reset link email never arrives** — set `RESEND_API_KEY` in `.env`, or use the printed recovery code instead.

## Repository layout

```
backend/
  app/               FastAPI application code
  db/                SQL schemas (SQLite + Postgres)
  scripts/           Seed, evaluation, fine-tuning
  runs/              Fine-tuning checkpoints (gitignored)
frontend/
  src/               React + Vite source
report/
  FYP_Report.tex     LaTeX source of the project report
  diagrams/          Architecture, ERD, sequence, analytics charts
data/                Invoice images + annotations (gitignored)
```

## Licence

Written for academic submission. Not currently licensed for reuse.
