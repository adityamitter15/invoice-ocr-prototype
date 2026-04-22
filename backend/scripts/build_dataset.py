#!/usr/bin/env python3
"""
build_dataset.py

Crops each row's description and amount cells from all the AGW receipt scans,
then writes an initial TrOCR prediction alongside each crop as a .txt file.
The .txt files are what you correct - either via the Review Queue or label_helper.py.

Usage:
    cd backend && source venv/bin/activate
    python scripts/build_dataset.py [--raw-dir PATH] [--crops-dir PATH] [--skip-existing]

Output per receipt:
    data/crops/{invoice_id}/row_{n:02d}_description.png  + .txt  (TrOCR guess)
    data/crops/{invoice_id}/row_{n:02d}_amount.png       + .txt
    data/crops/{invoice_id}/manifest.json

Takes ~3-5 min for 154 receipts on CPU. Use --skip-existing to resume if interrupted.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image, ImageOps

from app.ocr.handwriting import (
    DEFAULT_MAX_TOKENS,
    _load_handwritten,
    _ocr_with,
    _pil_to_cv_bgr,
    normalize_document,
)
from app.ocr.receipt_pipeline import (
    MAX_TABLE_ROWS,
    TARGET_H,
    _crop_cell,
    _has_ink,
    _resize_for_trocr,
    preprocess_cell_for_trocr,
    remove_grid_lines,
)
from app.ocr.region_detector import detect_regions, get_column_bounds


def build_dataset(raw_dir: Path, crops_dir: Path, skip_existing: bool = False) -> None:
    raw_dir   = Path(raw_dir)
    crops_dir = Path(crops_dir)

    image_paths = sorted(raw_dir.glob("*.JPG")) + sorted(raw_dir.glob("*.jpg"))
    if not image_paths:
        print(f"No images found in {raw_dir}")
        return

    print(f"Found {len(image_paths)} receipt images in {raw_dir}")
    print("Loading TrOCR model (first call may download weights)…")
    processor, model = _load_handwritten()
    print("Model loaded.\n")

    total_crops  = 0
    total_skipped = 0
    t0 = time.time()

    for img_idx, img_path in enumerate(image_paths, 1):
        invoice_id = img_path.stem
        out_dir    = crops_dir / invoice_id

        if skip_existing and (out_dir / "manifest.json").exists():
            print(f"[{img_idx:3d}/{len(image_paths)}] {invoice_id} - skipped (already done)")
            total_skipped += 1
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{img_idx:3d}/{len(image_paths)}] {invoice_id} …", end="", flush=True)

        pil_img = Image.open(img_path)
        pil_img = ImageOps.exif_transpose(pil_img).convert("RGB")
        pil_img = normalize_document(pil_img)

        cv_img = _pil_to_cv_bgr(pil_img)
        h, w   = cv_img.shape[:2]

        regions    = detect_regions(cv_img)
        col_bounds = get_column_bounds(w)

        row_ys      = regions["row_ys"]
        table_end_y = regions["table_end_y"]

        # Limit to 28 rows - same as inference pipeline
        row_pairs = [
            (row_ys[i], row_ys[i + 1])
            for i in range(min(len(row_ys) - 1, MAX_TABLE_ROWS))
        ]
        if row_ys and len(row_pairs) < MAX_TABLE_ROWS:
            row_pairs.append(
                (row_ys[min(len(row_ys) - 1, MAX_TABLE_ROWS)], table_end_y)
            )

        # Grid-line removal (same as inference)
        cleaned_rgb = remove_grid_lines(pil_img).convert("RGB")

        desc_x1, desc_x2 = col_bounds["description"]
        up_x1,   _       = col_bounds["unit_price"]
        _,       am_x2   = col_bounds["amount"]

        manifest = {
            "invoice_id":   invoice_id,
            "image":        img_path.name,
            "image_size":   [w, h],
            "rows_detected": len(row_pairs),
            "crops":        [],
        }

        saved = 0
        for row_idx, (y_top, y_bot) in enumerate(row_pairs, start=1):
            if y_bot - y_top < 8:
                continue

            # Skip blank rows (same logic as inference)
            desc_check = _crop_cell(cleaned_rgb, desc_x1, y_top, desc_x2, y_bot)
            if not _has_ink(desc_check):
                continue

            row_entry = {"row": row_idx, "crops": []}

            # ── Description crop ────────────────────────────────────────────
            desc_raw  = _crop_cell(cleaned_rgb, desc_x1 + 50, y_top, desc_x2, y_bot)
            desc_pre  = preprocess_cell_for_trocr(desc_raw)
            desc_in   = _resize_for_trocr(desc_pre)
            desc_pred = _ocr_with(processor, model, desc_in,
                                  max_new_tokens=DEFAULT_MAX_TOKENS)

            stem = f"row_{row_idx:02d}_description"
            desc_pre.save(out_dir / f"{stem}.png")
            (out_dir / f"{stem}.txt").write_text(desc_pred, encoding="utf-8")
            row_entry["crops"].append({"col": "description", "pred": desc_pred})

            # ── Amount crop (unit_price + amount combined) ───────────────────
            amt_raw  = _crop_cell(cleaned_rgb, up_x1, y_top, am_x2, y_bot)
            if _has_ink(amt_raw):
                amt_pre  = preprocess_cell_for_trocr(amt_raw)
                amt_in   = _resize_for_trocr(amt_pre)
                amt_pred = _ocr_with(processor, model, amt_in,
                                     max_new_tokens=DEFAULT_MAX_TOKENS)
                a_stem = f"row_{row_idx:02d}_amount"
                amt_pre.save(out_dir / f"{a_stem}.png")
                (out_dir / f"{a_stem}.txt").write_text(amt_pred, encoding="utf-8")
                row_entry["crops"].append({"col": "amount", "pred": amt_pred})

            manifest["crops"].append(row_entry)
            saved += 1

        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        elapsed = time.time() - t0
        per_img = elapsed / img_idx
        eta     = per_img * (len(image_paths) - img_idx)
        print(f"  {saved} crops  (ETA {int(eta//60)}m {int(eta%60)}s)")
        total_crops += saved

    print(f"\n{'='*60}")
    print(f"Done.  {total_crops} crops saved across {len(image_paths) - total_skipped} receipts.")
    print(f"Skipped {total_skipped} already-processed receipts.")
    print(f"Crops saved to: {crops_dir}")
    print()
    print("NEXT STEP - correct the .txt labels:")
    print("  Run:  python scripts/label_helper.py")
    print("  Or manually edit each .txt file to match the handwriting in the .png")
    print()
    print("THEN fine-tune:")
    print("  python scripts/finetune_trocr.py")


def main():
    parser = argparse.ArgumentParser(description="Build TrOCR fine-tuning dataset")
    parser.add_argument("--raw-dir",      default=None, help="Raw receipt JPGs directory")
    parser.add_argument("--crops-dir",    default=None, help="Output directory for crops")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip receipts that already have a manifest.json")
    args = parser.parse_args()

    backend_root = Path(__file__).resolve().parents[1]
    data_root    = backend_root.parent / "data"

    raw_dir   = Path(args.raw_dir)   if args.raw_dir   else data_root / "raw"
    crops_dir = Path(args.crops_dir) if args.crops_dir else data_root / "crops"

    build_dataset(raw_dir, crops_dir, skip_existing=args.skip_existing)


if __name__ == "__main__":
    main()
