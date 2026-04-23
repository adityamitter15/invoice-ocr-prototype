#!/usr/bin/env python3
"""
extract_labels_from_db.py

Pulls the human-corrected descriptions from approved invoices and writes them
back into the crop .txt files so they can be used as training data.

The idea is that the Review Queue doubles as a labelling tool - when you correct
a wrong description and approve the invoice, those corrections land in the DB.
This script extracts them into the file format finetune_trocr.py expects.

Usage:
    cd backend && source venv/bin/activate
    python scripts/extract_labels_from_db.py [--dry-run]

Then run:
    python scripts/finetune_trocr.py
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import get_connection, is_sqlite_conn

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
CROPS_DIR = DATA_ROOT / "crops"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be written without actually writing")
    parser.add_argument("--crops-dir", default=None)
    args = parser.parse_args()

    crops_dir = Path(args.crops_dir) if args.crops_dir else CROPS_DIR

    conn = get_connection()
    cur  = conn.cursor()
    ph   = "?" if is_sqlite_conn(conn) else "%s"

    # Pull all approved submissions with their extracted_data
    cur.execute(
        "SELECT id, extracted_data FROM submissions WHERE status = 'approved' "
        "ORDER BY created_at"
    )
    submissions = [dict(r) for r in cur.fetchall()]

    # Pull all approved invoice items (human-corrected descriptions)
    cur.execute(
        "SELECT ii.description, ii.amount, ii.quantity, i.submission_id "
        "FROM invoice_items ii "
        "JOIN invoices i ON i.id = ii.invoice_id "
        "WHERE ii.description IS NOT NULL AND ii.description != '' "
        "ORDER BY i.submission_id, ii.rowid"
    )
    items = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    print(f"Found {len(submissions)} approved submissions")
    print(f"Found {len(items)} line items with descriptions")

    # Group items by submission_id
    by_sub = {}
    for item in items:
        sid = str(item["submission_id"])
        by_sub.setdefault(sid, []).append(item)

    total_written  = 0
    total_skipped  = 0
    total_notfound = 0

    for sub in submissions:
        sub_id = str(sub["id"])
        ed     = sub["extracted_data"]
        if isinstance(ed, str):
            try:
                ed = json.loads(ed)
            except Exception:
                ed = {}

        structured = ed.get("structured", {})
        ocr_items  = structured.get("line_items", [])
        db_items   = by_sub.get(sub_id, [])

        if not db_items:
            continue

        # Find crop directory for this submission
        # Crops are saved by invoice_id (filename stem), not submission UUID.
        # We look for a manifest in any crop dir that mentions this submission.
        crop_dir = None
        for manifest_path in sorted(crops_dir.glob("*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text())
                if manifest.get("invoice_id") == manifest_path.parent.name:
                    # Check if the OCR data matches (invoice number)
                    inv_no = structured.get("invoice_number", "")
                    if inv_no and inv_no in str(manifest_path.parent.name):
                        crop_dir = manifest_path.parent
                        break
            except Exception:
                continue

        # Fallback: match by row count similarity
        if not crop_dir:
            for manifest_path in sorted(crops_dir.glob("*/manifest.json")):
                try:
                    manifest = json.loads(manifest_path.read_text())
                    n_crops = len(manifest.get("crops", []))
                    if abs(n_crops - len(db_items)) <= 3:
                        crop_dir = manifest_path.parent
                        break
                except Exception:
                    continue

        if not crop_dir:
            print(f"  [SKIP] submission {sub_id[:8]}... - no matching crop directory")
            total_notfound += 1
            continue

        # Match DB items to crop files by row order
        crop_txts = sorted(crop_dir.glob("row_*_description.txt"))

        print(f"\n  Submission {sub_id[:8]}  ->  {crop_dir.name}  "
              f"({len(db_items)} items, {len(crop_txts)} crops)")

        for i, db_item in enumerate(db_items):
            desc = db_item["description"].strip()
            if not desc:
                continue

            if i < len(crop_txts):
                txt_path = crop_txts[i]
                old_text = txt_path.read_text(encoding="utf-8").strip()

                if old_text == desc:
                    total_skipped += 1
                    continue

                print(f"    row {i+1:2d}:  {old_text!r}  ->  {desc!r}")

                if not args.dry_run:
                    txt_path.write_text(desc, encoding="utf-8")
                total_written += 1
            else:
                print(f"    row {i+1:2d}:  no crop file found for {desc!r}")
                total_notfound += 1

    print(f"\n{'='*60}")
    if args.dry_run:
        print(f"DRY RUN - nothing written")
    else:
        print(f"Done.")
    print(f"  Labels written:    {total_written}")
    print(f"  Already correct:   {total_skipped}")
    print(f"  No crop found:     {total_notfound}")

    if total_written == 0 and not args.dry_run:
        print()
        print("No new labels written.  Tip:")
        print("  Go to the Review Queue, correct any wrong fields, and approve invoices.")
        print("  Each approved invoice adds labels for fine-tuning.")
    else:
        print()
        print("Next:  python scripts/finetune_trocr.py")


if __name__ == "__main__":
    main()
