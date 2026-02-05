# Invoice OCR Prototype (FastAPI + React)

A small prototype demonstrating an invoice OCR + Human-in-the-Loop (HITL) review flow:

- Upload invoice image → OCR runs → stored as `pending_review`
- Approve submission → stored as `approved` + invoice items written
- Database: PostgreSQL (Supabase) primary, automatic SQLite fallback for reliable demos

---

## Quick Start (Local)

### 1) Backend (FastAPI)
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

Backend runs at:
	•	http://127.0.0.1:8000

Useful endpoints:
	•	GET  /health
	•	POST /submissions/upload (multipart form upload)
	•	GET  /submissions?status=pending_review
	•	GET  /submissions?status=approved
	•	GET  /submissions/{id}
	•	POST /submissions/{id}/approve

⸻

2) Frontend (React + Vite)

cd frontend
npm install
npm run dev


Frontend runs at:
	•	http://localhost:5173

⸻

Environment Variables

Backend database

Create backend/.env (use backend/.env.example as a template).

The backend supports:
	•	PostgreSQL (Supabase) primary: uses Postgres when reachable
	•	SQLite fallback: if Postgres is unreachable (e.g., university Wi-Fi blocks Supabase), it automatically falls back to SQLite at backend/local.db so the demo still works

Example (PostgreSQL / Supabase):

DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<db>

Example (SQLite explicit):

DATABASE_URL=sqlite:///local.db

Frontend API base URL

Create frontend/.env:

VITE_API_BASE_URL=http://127.0.0.1:8000


Demo Flow (for marking)
	1.	Start backend and frontend.
	2.	Upload an invoice image (frontend UI).
	3.	Submission appears in pending_review queue.
	4.	Open the submission to review OCR output.
	5.	Approve submission → it moves to approved.

⸻

Troubleshooting

Frontend shows “Queue fetch failed (500/503)”
	•	Make sure the backend is running (uvicorn terminal still open)
	•	Check backend terminal logs for the real error
	•	If it mentions a PostgreSQL timeout/network issue: try hotspot/VPN, or rely on the automatic SQLite fallback

Reset local SQLite demo DB (optional)

cd backend
rm -f local.db
sqlite3 local.db < db/schema_sqlite.sql