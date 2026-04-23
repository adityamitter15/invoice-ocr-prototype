#!/usr/bin/env python3
"""
Ablation study: compare Tesseract-only, EasyOCR-only and the combined
multi-engine pipeline on the evaluation crops.

This is the experimental scaffolding referenced in Section 7.1 of the
report. It loads the HITL-corrected subset of crops (those whose stored
label differs from what raw TrOCR would predict), then evaluates each
engine independently so the design choice of routing by content type
can be justified against single-engine baselines.

Important: this script needs a labelled ground-truth set to produce
meaningful numbers. When run against the current dataset, where most
labels are unrevised TrOCR predictions, the results measure agreement
rather than accuracy (same caveat as evaluate_pipeline.py).

Usage:
    cd backend && source venv/bin/activate
    python scripts/ablation.py [--crops-dir PATH] [--limit N]
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
CROPS_DIR = DATA_ROOT / "crops"


def _cer(pred: str, ref: str) -> float:
    """Character Error Rate via Levenshtein distance."""
    pred, ref = pred.strip().lower(), ref.strip().lower()
    if not ref:
        return 0.0 if not pred else 1.0
    m, n = len(ref), len(pred)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if ref[i - 1] == pred[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[m][n] / max(len(ref), 1)


def load_pairs(crops_dir: Path, col: str = "description") -> List[Tuple[Path, str]]:
    """Load every labelled crop of the given column as (image_path, label)."""
    pairs: List[Tuple[Path, str]] = []
    for txt in sorted(crops_dir.rglob(f"*_{col}.txt")):
        img = txt.with_suffix(".png")
        if not img.exists():
            continue
        label = txt.read_text(encoding="utf-8").strip()
        if label:
            pairs.append((img, label))
    return pairs


def _report(i: int, total: int, scores: list, t0: float) -> None:
    """Print a one-line progress update every 100 crops."""
    if i and (i % 100 == 0 or i == total):
        elapsed = time.time() - t0
        per = elapsed / i
        eta = per * (total - i)
        mean_so_far = sum(scores) / len(scores)
        print(
            f"  [{i}/{total}] mean CER so far: {mean_so_far:.3f}  "
            f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)",
            flush=True,
        )


def evaluate_engine(engine: str, pairs: List[Tuple[Path, str]]) -> dict:
    """Run one engine across all crops and return aggregate CER."""
    import numpy as np

    total = len(pairs)
    scores = []
    t0 = time.time()

    if engine == "tesseract":
        import pytesseract
        for i, (img_path, truth) in enumerate(pairs, 1):
            pil = Image.open(img_path).convert("RGB")
            pred = pytesseract.image_to_string(pil, config="--psm 7 --oem 3").strip()
            scores.append(_cer(pred, truth))
            _report(i, total, scores, t0)
    elif engine == "easyocr":
        import easyocr
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        for i, (img_path, truth) in enumerate(pairs, 1):
            pil = Image.open(img_path).convert("RGB")
            arr = np.array(pil)
            result = reader.readtext(arr, detail=0, paragraph=False)
            pred = " ".join(result).strip()
            scores.append(_cer(pred, truth))
            _report(i, total, scores, t0)
    elif engine == "trocr":
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        import torch
        proc = TrOCRProcessor.from_pretrained("microsoft/trocr-large-handwritten")
        model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-large-handwritten")
        model.eval()
        for i, (img_path, truth) in enumerate(pairs, 1):
            pil = Image.open(img_path).convert("RGB")
            pv = proc(images=pil, return_tensors="pt").pixel_values
            with torch.no_grad():
                ids = model.generate(pv, max_new_tokens=64)
            pred = proc.batch_decode(ids, skip_special_tokens=True)[0].strip()
            scores.append(_cer(pred, truth))
            _report(i, total, scores, t0)
    else:
        raise ValueError(f"Unknown engine: {engine}")

    return {
        "engine": engine,
        "n_samples": len(pairs),
        "mean_cer": round(float(np.mean(scores)), 4),
        "median_cer": round(float(np.median(scores)), 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Single-engine ablation on evaluation crops")
    parser.add_argument("--crops-dir", default=None)
    parser.add_argument("--col", default="description")
    parser.add_argument("--limit", type=int, default=None, help="Cap number of crops for a quick run")
    parser.add_argument("--save-json", action="store_true")
    args = parser.parse_args()

    crops_dir = Path(args.crops_dir) if args.crops_dir else CROPS_DIR
    pairs = load_pairs(crops_dir, col=args.col)
    if args.limit:
        pairs = pairs[: args.limit]

    print(f"Ablation over {len(pairs)} crops (column: {args.col})\n", flush=True)

    results = {}
    for engine in ("tesseract", "easyocr", "trocr"):
        print(f"Evaluating {engine}...", flush=True)
        try:
            results[engine] = evaluate_engine(engine, pairs)
        except Exception as exc:
            print(f"  {engine} failed: {exc}", flush=True)
            results[engine] = {"engine": engine, "error": str(exc)}
        if "mean_cer" in results[engine]:
            r = results[engine]
            print(f"  mean CER: {r['mean_cer']:.4f}  median: {r['median_cer']:.4f}", flush=True)
        print(flush=True)

    if args.save_json:
        out = DATA_ROOT / "trocr-finetuned" / "ablation_results.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"Results saved to: {out}")


if __name__ == "__main__":
    main()
