import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

# Load variables from backend/.env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Add it to backend/.env")

def get_connection():
    """
    Returns a new Postgres connection.
    Uses RealDictCursor so queries return dict-like rows.
    """
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)