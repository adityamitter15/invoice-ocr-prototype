HOW TO RUN THE PROTOTYPE (LOCAL)

1. Backend (FastAPI)
-------------------
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

Backend runs at:
http://127.0.0.1:8000


2. Frontend (React + Vite)
-------------------------
cd frontend
npm install
npm run dev

Frontend runs at:
http://localhost:5173



---

ENVIRONMENT VARIABLES (IMPORTANT)

Backend database:
Create a file called backend/.env and add:

DATABASE_URL=postgresql://postgres.wzjqsdrcbukolsxwmaug:j3i5bB7YULDpiZKm@aws-1-eu-west-2.pooler.supabase.com:6543/postgres

Frontend API base URL:
Create a file called frontend/.env and add:

VITE_API_BASE_URL=http://127.0.0.1:8000

---

TROUBLESHOOTING

If the frontend shows “Queue fetch failed (500/503)”:
- Make sure the backend is running (uvicorn terminal still open)
- Check backend terminal logs for the real error
- If it mentions database timeout, your network may be blocking Supabase (uni Wi-Fi). Use hotspot/VPN.