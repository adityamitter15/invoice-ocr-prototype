#!/usr/bin/env python3
"""
test_receipt_pipeline.py - Run the full receipt pipeline on a single image
                            and print a human-readable summary.

Usage:
    cd backend && source venv/bin/activate
    python scripts/test_receipt_pipeline.py data/raw/000001.JPG
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ocr.receipt_pipeline import process_receipt


def fmt(val: str, width: int = 0) -> str:
    v = (val or "").strip()
    return v.ljust(width) if width else v


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_receipt_pipeline.py <image_path>")
        sys.exit(1)

    img_path = Path(sys.argv[1])
    if not img_path.exists():
        print(f"File not found: {img_path}")
        sys.exit(1)

    print(f"\nProcessing: {img_path.name}")
    print("─" * 72)

    result = process_receipt(img_path.read_bytes())

    # ── Header fields ────────────────────────────────────────────────────────
    print(f"Invoice No : {result.get('invoice_number', '')}")
    print(f"Date       : {result.get('invoice_date', '')}")
    cust = result.get("customer", {})
    print(f"Customer   : {cust.get('name', '')}")
    print(f"Phone      : {cust.get('phone', '')}")
    print()

    # ── Line items ───────────────────────────────────────────────────────────
    items = result.get("line_items", [])
    col_q   = 4
    col_d   = 52
    col_p   = 12
    col_a   = 12

    header = (f"{'Row':>3}  {'QTY':>{col_q}}  {'DESCRIPTION':<{col_d}}"
              f"  {'UNIT PRICE':>{col_p}}  {'AMOUNT':>{col_a}}")
    print(header)
    print("─" * len(header))

    non_empty = 0
    for item in items:
        qty   = fmt(item.get("quantity",   ""), col_q)
        desc  = fmt(item.get("description",""), col_d)
        price = fmt(item.get("unit_price", ""), col_p)
        amt   = fmt(item.get("amount",     ""), col_a)
        row   = item.get("row", "")
        # Only print rows that have at least some content
        if any([item.get("quantity"), item.get("description"),
                item.get("unit_price"), item.get("amount")]):
            print(f"{row:>3}  {qty}  {desc}  {price}  {amt}")
            non_empty += 1

    print("─" * len(header))
    print(f"     {non_empty} non-empty rows  "
          f"({len(items)} total detected)")
    print()

    # ── Totals ───────────────────────────────────────────────────────────────
    print(f"Net Total  : {result.get('net_total',  '')}")
    print(f"VAT        : {result.get('vat',         '')}")
    print(f"Amount Due : {result.get('amount_due',  '')}")
    print()

    # ── Printed header text (Tesseract) ──────────────────────────────────────
    print("── Printed header (Tesseract) " + "─" * 42)
    print(result.get("raw_text", "").split("[CUSTOMER]")[0].replace("[HEADER]\n", "").strip())


if __name__ == "__main__":
    main()
