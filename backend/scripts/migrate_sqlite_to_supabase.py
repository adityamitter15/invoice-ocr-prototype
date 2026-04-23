#!/usr/bin/env python3
"""
migrate_sqlite_to_supabase.py

Copies all data from local SQLite (local.db) -> Supabase PostgreSQL.
Safe to re-run: uses ON CONFLICT DO NOTHING so existing rows are skipped.

Usage:
    cd backend && source venv/bin/activate
    python scripts/migrate_sqlite_to_supabase.py
    python scripts/migrate_sqlite_to_supabase.py --dry-run   # preview only
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=True)

SQLITE_PATH = Path(__file__).resolve().parents[1] / "local.db"
DATABASE_URL = os.getenv("DATABASE_URL")


def get_sqlite():
    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_postgres():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        connect_timeout=10,
        sslmode="require",
    )


def migrate(dry_run: bool):
    print(f"\n{'DRY RUN - ' if dry_run else ''}Migrating SQLite -> Supabase\n{'='*50}")

    sqlite = get_sqlite()
    pg = get_postgres()
    pg_cur = pg.cursor()

    counts = {"submissions": 0, "invoices": 0, "invoice_items": 0,
              "products": 0, "stock_movements": 0}

    # Submissions
    rows = [dict(r) for r in sqlite.execute(
        "SELECT id, image_url, extracted_data, status, created_at FROM submissions"
    ).fetchall()]
    print(f"\nSubmissions: {len(rows)} rows")
    for r in rows:
        ed = r["extracted_data"]
        if isinstance(ed, str):
            try: ed = json.loads(ed)
            except: ed = {}
        if not dry_run:
            pg_cur.execute(
                "INSERT INTO submissions (id, image_url, extracted_data, status, created_at) "
                "VALUES (%s, %s, %s::jsonb, %s, %s) ON CONFLICT (id) DO NOTHING",
                (r["id"], r["image_url"], json.dumps(ed), r["status"], r["created_at"])
            )
        counts["submissions"] += 1

    # Invoices
    rows = [dict(r) for r in sqlite.execute(
        "SELECT id, submission_id, invoice_number, invoice_date, customer_name, "
        "       customer_phone, net_total, vat, amount_due, created_at FROM invoices"
    ).fetchall()]
    print(f"Invoices:    {len(rows)} rows")
    for r in rows:
        if not dry_run:
            pg_cur.execute(
                "INSERT INTO invoices (id, submission_id, invoice_number, invoice_date, "
                "  customer_name, customer_phone, net_total, vat, amount_due, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (r["id"], r["submission_id"], r["invoice_number"], r["invoice_date"],
                 r["customer_name"], r["customer_phone"], r["net_total"], r["vat"],
                 r["amount_due"], r["created_at"])
            )
        counts["invoices"] += 1

    # Invoice items
    rows = [dict(r) for r in sqlite.execute(
        "SELECT id, submission_id, invoice_id, description, quantity, "
        "       unit_price, amount, confidence FROM invoice_items"
    ).fetchall()]
    print(f"Items:       {len(rows)} rows")
    for r in rows:
        if not dry_run:
            pg_cur.execute(
                "INSERT INTO invoice_items (id, submission_id, invoice_id, description, "
                "  quantity, unit_price, amount, confidence) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (r["id"], r["submission_id"], r["invoice_id"], r["description"],
                 r["quantity"], r["unit_price"], r["amount"], r["confidence"])
            )
        counts["invoice_items"] += 1

    # Products
    rows = [dict(r) for r in sqlite.execute(
        "SELECT id, name, current_stock FROM products"
    ).fetchall()]
    print(f"Products:    {len(rows)} rows")
    for r in rows:
        if not dry_run:
            pg_cur.execute(
                "INSERT INTO products (id, name, current_stock) "
                "VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (r["id"], r["name"], r["current_stock"])
            )
        counts["products"] += 1

    # Stock movements
    rows = [dict(r) for r in sqlite.execute(
        "SELECT id, product_id, submission_id, quantity_change, created_at "
        "FROM stock_movements"
    ).fetchall()]
    print(f"Movements:   {len(rows)} rows")
    for r in rows:
        if not dry_run:
            pg_cur.execute(
                "INSERT INTO stock_movements (id, product_id, submission_id, "
                "  quantity_change, created_at) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (r["id"], r["product_id"], r["submission_id"],
                 r["quantity_change"], r["created_at"])
            )
        counts["stock_movements"] += 1

    if not dry_run:
        pg.commit()
        print(f"\nMigration complete.")
    else:
        print(f"\nDry run complete - nothing written.")

    print(f"  Submissions:     {counts['submissions']}")
    print(f"  Invoices:        {counts['invoices']}")
    print(f"  Invoice items:   {counts['invoice_items']}")
    print(f"  Products:        {counts['products']}")
    print(f"  Stock movements: {counts['stock_movements']}")

    pg_cur.close()
    pg.close()
    sqlite.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not DATABASE_URL or DATABASE_URL.startswith("sqlite"):
        print("ERROR: DATABASE_URL must point to Supabase PostgreSQL.")
        sys.exit(1)

    migrate(dry_run=args.dry_run)
