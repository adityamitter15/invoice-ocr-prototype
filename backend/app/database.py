import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

# -------------------------------------------------------------------
# Force-load backend/.env explicitly and override any shell variables
# -------------------------------------------------------------------
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Ensure backend/.env exists and is correct."
    )

def get_connection():
    """
    Create and return a PostgreSQL connection.

    - Uses RealDictCursor so rows return as dicts
    - Uses connect_timeout to avoid hanging indefinitely
    - Forces SSL (required by Supabase pooler)
    """
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        connect_timeout=5,
        sslmode="require",
    )