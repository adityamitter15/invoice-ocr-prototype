#!/usr/bin/env python3
"""
evaluate_pipeline.py

Runs both the base TrOCR model and the fine-tuned version against the
corrected crop labels and computes CER (Character Error Rate) and word
accuracy for each. Use --save-json to write the results to a file that
the web dashboard can display.

Usage:
    cd backend && source venv/bin/activate
    python scripts/evaluate_pipeline.py
    python scripts/evaluate_pipeline.py --save-json
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

DATA_ROOT  = Path(__file__).resolve().parents[2] / "data"
CROPS_DIR  = DATA_ROOT / "crops"
OUTPUT_DIR = DATA_ROOT / "trocr-finetuned"


def _cer(pred: str, ref: str) -> float:
    """Character Error Rate via Levenshtein distance."""
    pred, ref = pred.strip().lower(), ref.strip().lower()
    if not ref:
        return 0.0 if not pred else 1.0
    m, n = len(ref), len(pred)
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m+1): dp[i][0] = i
    for j in range(n+1): dp[0][j] = j
    for i in range(1, m+1):
        for j in range(1, n+1):
            cost = 0 if ref[i-1]==pred[j-1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    return dp[m][n] / max(len(ref), 1)


def _wer(pred: str, ref: str) -> float:
    """Word Error Rate."""
    pred_words = pred.strip().lower().split()
    ref_words  = ref.strip().lower().split()
    if not ref_words:
        return 0.0 if not pred_words else 1.0
    m, n = len(ref_words), len(pred_words)
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m+1): dp[i][0] = i
    for j in range(n+1): dp[0][j] = j
    for i in range(1, m+1):
        for j in range(1, n+1):
            cost = 0 if ref_words[i-1]==pred_words[j-1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    return dp[m][n] / max(len(ref_words), 1)


def load_corrected_pairs(crops_dir: Path, col: str = "description") -> List[Tuple[Path, str]]:
    """Load crops that have human-corrected labels."""
    pairs = []
    for txt in sorted(crops_dir.rglob(f"*_{col}.txt")):
        img = txt.with_suffix(".png")
        if not img.exists():
            continue
        label = txt.read_text(encoding="utf-8").strip()
        if label:
            pairs.append((img, label))
    return pairs


def evaluate_model(model_name: str, pairs: List[Tuple[Path, str]], target_h: int = 64) -> dict:
    """Run a model on all crops and compute CER/WER vs ground truth."""
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel

    print(f"\n  Loading: {model_name}")
    processor = TrOCRProcessor.from_pretrained(model_name)
    model     = VisionEncoderDecoderModel.from_pretrained(model_name)
    model.eval()

    cer_scores  = []
    wer_scores  = []
    exact_match = 0
    examples    = []

    for i, (img_path, ground_truth) in enumerate(pairs):
        pil_img = Image.open(img_path).convert("RGB")
        w, h = pil_img.size
        if h > 0:
            scale   = target_h / h
            pil_img = pil_img.resize((max(1, int(w*scale)), target_h), Image.LANCZOS)

        pixel_values = processor(images=pil_img, return_tensors="pt").pixel_values
        import torch
        with torch.no_grad():
            ids = model.generate(pixel_values, max_new_tokens=64)
        pred = processor.batch_decode(ids, skip_special_tokens=True)[0].strip()

        cer = _cer(pred, ground_truth)
        wer = _wer(pred, ground_truth)
        cer_scores.append(cer)
        wer_scores.append(wer)
        if pred.strip().lower() == ground_truth.strip().lower():
            exact_match += 1

        if i < 5 or (cer > 0.5 and len(examples) < 10):
            examples.append({
                "crop":   str(img_path.relative_to(img_path.parent.parent.parent)),
                "pred":   pred,
                "truth":  ground_truth,
                "cer":    round(cer, 3),
            })

        if (i + 1) % 50 == 0:
            print(f"    [{i+1}/{len(pairs)}]  avg CER so far: {sum(cer_scores)/len(cer_scores):.3f}")

    import numpy as np
    return {
        "model":       model_name,
        "n_samples":   len(pairs),
        "mean_cer":    round(float(np.mean(cer_scores)),  4),
        "median_cer":  round(float(np.median(cer_scores)), 4),
        "mean_wer":    round(float(np.mean(wer_scores)),  4),
        "exact_match": round(exact_match / len(pairs),    4),
        "word_acc":    round(exact_match / len(pairs) * 100, 1),
        "examples":    examples,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crops-dir",  default=None)
    parser.add_argument("--finetuned",  default=None,
                        help="Path to fine-tuned model (default: data/trocr-finetuned/final)")
    parser.add_argument("--col",        default="description")
    parser.add_argument("--save-json",  action="store_true")
    parser.add_argument("--skip-base",  action="store_true",
                        help="Skip base model evaluation (faster if you already have results)")
    args = parser.parse_args()

    crops_dir   = Path(args.crops_dir)  if args.crops_dir  else CROPS_DIR
    finetuned   = Path(args.finetuned)  if args.finetuned  else OUTPUT_DIR / "final"
    base_model  = os.getenv("TROCR_HANDWRITTEN_MODEL", "microsoft/trocr-large-handwritten")

    pairs = load_corrected_pairs(crops_dir, col=args.col)
    if not pairs:
        print(f"No corrected crops found in {crops_dir}")
        print("Run build_dataset.py + label_helper.py first.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  TrOCR Evaluation  ({args.col} column)")
    print(f"  {len(pairs)} corrected crops")
    print(f"{'='*60}")

    results = {}

    # ── Base model ────────────────────────────────────────────────────────
    if not args.skip_base:
        print("\n[1/2] Evaluating BASE model (no fine-tuning)…")
        results["base"] = evaluate_model(base_model, pairs)
        r = results["base"]
        print(f"\n  Base model results:")
        print(f"    Mean CER:    {r['mean_cer']:.3f}  ({(1-r['mean_cer'])*100:.1f}% char accuracy)")
        print(f"    Mean WER:    {r['mean_wer']:.3f}")
        print(f"    Exact match: {r['word_acc']}%")
    else:
        print("\n[1/2] Skipping base model evaluation.")

    # ── Fine-tuned model ──────────────────────────────────────────────────
    if finetuned.exists():
        print(f"\n[2/2] Evaluating FINE-TUNED model ({finetuned})…")
        results["finetuned"] = evaluate_model(str(finetuned), pairs)
        r = results["finetuned"]
        print(f"\n  Fine-tuned model results:")
        print(f"    Mean CER:    {r['mean_cer']:.3f}  ({(1-r['mean_cer'])*100:.1f}% char accuracy)")
        print(f"    Mean WER:    {r['mean_wer']:.3f}")
        print(f"    Exact match: {r['word_acc']}%")
    else:
        print(f"\n[2/2] Fine-tuned model not found at {finetuned}")
        print("Run finetune_trocr.py first.")

    # ── Comparison ────────────────────────────────────────────────────────
    if "base" in results and "finetuned" in results:
        base_cer = results["base"]["mean_cer"]
        ft_cer   = results["finetuned"]["mean_cer"]
        improvement = (base_cer - ft_cer) / base_cer * 100

        print(f"\n{'='*60}")
        print(f"  IMPROVEMENT SUMMARY")
        print(f"{'='*60}")
        print(f"  Base CER:       {base_cer:.3f}  ({(1-base_cer)*100:.1f}% char accuracy)")
        print(f"  Fine-tuned CER: {ft_cer:.3f}  ({(1-ft_cer)*100:.1f}% char accuracy)")
        print(f"  CER reduction:  {improvement:.1f}%")
        print()
        base_wa   = results["base"]["word_acc"]
        ft_wa     = results["finetuned"]["word_acc"]
        print(f"  Base exact match:       {base_wa}%")
        print(f"  Fine-tuned exact match: {ft_wa}%")
        print(f"  Word accuracy gain:     +{ft_wa - base_wa:.1f}%")

    if args.save_json:
        out = OUTPUT_DIR / "evaluation_results.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nResults saved to: {out}")

    print()


if __name__ == "__main__":
    main()
