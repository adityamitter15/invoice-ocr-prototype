#!/usr/bin/env python3
"""
finetune_trocr.py - Fine-tunes TrOCR on the annotated AGW receipt crops.

Steps before running this:
  1. python scripts/build_dataset.py  (generates crops + initial TrOCR guesses)
  2. Correct the .txt files via the Review Queue or label_helper.py
  3. cd backend && source venv/bin/activate
     python scripts/finetune_trocr.py [--epochs 15] [--batch-size 8]

Checkpoints saved to data/trocr-finetuned/
Best model saved to data/trocr-finetuned/final/

Switch the pipeline to use the fine-tuned model:
    export TROCR_HANDWRITTEN_MODEL=/path/to/data/trocr-finetuned/final
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset
from transformers import (
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
    TrOCRProcessor,
    VisionEncoderDecoderModel,
    default_data_collator,
    EarlyStoppingCallback,
    TrainerCallback,
)

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

BASE_MODEL  = os.getenv("TROCR_HANDWRITTEN_MODEL", "microsoft/trocr-large-handwritten")
DATA_ROOT   = Path(__file__).resolve().parents[2] / "data"
CROPS_DIR   = DATA_ROOT / "crops"
OUTPUT_DIR  = DATA_ROOT / "trocr-finetuned"
TARGET_H    = 64


# ─────────────────────────────────────────────────────────────────────────────
# Dataset
# ─────────────────────────────────────────────────────────────────────────────

def _load_pairs(crops_dir: Path, col_filter: str = None) -> List[Tuple[Path, str]]:
    """
    Walk crops_dir for (image_path, label) pairs.

    Only includes pairs where the .txt has been CORRECTED - detected by
    checking if the label looks like a real correction vs a raw TrOCR
    prediction.  Any non-empty .txt is accepted; empty files are skipped.

    col_filter: if set (e.g. "description"), only load that column type.
    """
    pairs: List[Tuple[Path, str]] = []
    for txt_path in sorted(crops_dir.rglob("*.txt")):
        if txt_path.name == "manifest.json":
            continue
        if col_filter and f"_{col_filter}" not in txt_path.stem:
            continue
        img_path = txt_path.with_suffix(".png")
        if not img_path.exists():
            continue
        label = txt_path.read_text(encoding="utf-8").strip()
        if label:
            pairs.append((img_path, label))
    return pairs


class ReceiptCellDataset(Dataset):
    """
    PyTorch dataset that loads the crop PNGs and their corrected label TXTs.
    Augmentation is applied at training time to help the model generalise
    across different handwriting styles and scan quality.
    """

    def __init__(
        self,
        pairs: List[Tuple[Path, str]],
        processor: TrOCRProcessor,
        augment: bool = False,
    ):
        self.pairs     = pairs
        self.processor = processor
        self.augment   = augment

    def __len__(self) -> int:
        return len(self.pairs)

    def _augment(self, img: Image.Image) -> Image.Image:
        """Small random transforms to make training more robust."""
        import random
        from PIL import ImageEnhance, ImageFilter

        # Small random rotation (±3°)
        if random.random() < 0.5:
            angle = random.uniform(-3, 3)
            img = img.rotate(angle, fillcolor=255, expand=False)

        # Brightness jitter
        if random.random() < 0.5:
            factor = random.uniform(0.8, 1.2)
            img = ImageEnhance.Brightness(img).enhance(factor)

        # Slight sharpening or blurring
        if random.random() < 0.3:
            img = img.filter(ImageFilter.GaussianBlur(radius=0.5))

        return img

    def __getitem__(self, idx: int):
        img_path, label = self.pairs[idx]

        pil_img = Image.open(img_path).convert("RGB")

        # Resize to TrOCR input height
        w, h = pil_img.size
        if h > 0:
            scale   = TARGET_H / h
            pil_img = pil_img.resize((max(1, int(w * scale)), TARGET_H), Image.LANCZOS)

        if self.augment:
            pil_img = self._augment(pil_img)

        pixel_values = self.processor(
            images=pil_img, return_tensors="pt"
        ).pixel_values.squeeze(0)

        # Tokenise label
        label_enc = self.processor.tokenizer(
            text=label,
            return_tensors="pt",
            padding="max_length",
            max_length=64,
            truncation=True,
        )
        labels = label_enc.input_ids.squeeze(0)
        # Mask padding so it's excluded from the loss
        labels[labels == self.processor.tokenizer.pad_token_id] = -100

        return {"pixel_values": pixel_values, "labels": labels}


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

def _cer(pred: str, ref: str) -> float:
    """Character Error Rate."""
    if not ref:
        return 0.0 if not pred else 1.0
    # Simple edit distance
    m, n = len(ref), len(pred)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): dp[i][0] = i
    for j in range(n + 1): dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if ref[i-1] == pred[j-1] else 1
            dp[i][j] = min(dp[i-1][j]+1, dp[i][j-1]+1, dp[i-1][j-1]+cost)
    return dp[m][n] / max(len(ref), 1)


def make_compute_metrics(processor):
    def compute_metrics(eval_preds):
        preds, labels = eval_preds

        # Replace -100 padding
        labels = np.where(labels != -100, labels, processor.tokenizer.pad_token_id)

        decoded_preds  = processor.batch_decode(preds,   skip_special_tokens=True)
        decoded_labels = processor.batch_decode(labels,  skip_special_tokens=True)

        cer_scores = [_cer(p.strip(), l.strip())
                      for p, l in zip(decoded_preds, decoded_labels)]

        # Word accuracy
        word_acc = sum(
            p.strip().lower() == l.strip().lower()
            for p, l in zip(decoded_preds, decoded_labels)
        ) / max(len(decoded_preds), 1)

        return {
            "cer":       round(float(np.mean(cer_scores)), 4),
            "word_acc":  round(float(word_acc),            4),
        }

    return compute_metrics


# ─────────────────────────────────────────────────────────────────────────────
# Live-progress callback - writes training_stats.json after every epoch so the
# web dashboard can show the loss curve updating in real time.
# ─────────────────────────────────────────────────────────────────────────────

class LiveStatsCallback(TrainerCallback):
    def __init__(self, output_dir: Path, meta: dict):
        self.output_dir = output_dir
        self.meta = meta

    def on_epoch_end(self, args, state, control, **kwargs):
        stats = {**self.meta, "log_history": state.log_history,
                 "current_epoch": round(state.epoch or 0, 1),
                 "training_complete": False}
        try:
            (self.output_dir / "training_stats.json").write_text(
                json.dumps(stats, indent=2), encoding="utf-8"
            )
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Training
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fine-tune TrOCR on AGW receipt crops")
    parser.add_argument("--crops-dir",  default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--epochs",     type=int,   default=15)
    parser.add_argument("--batch-size", type=int,   default=8)
    parser.add_argument("--lr",         type=float, default=5e-5)
    parser.add_argument("--col",        default="description",
                        help="Column to train on: description | amount | all")
    parser.add_argument("--no-augment", action="store_true")
    args = parser.parse_args()

    crops_dir  = Path(args.crops_dir)  if args.crops_dir  else CROPS_DIR
    output_dir = Path(args.output_dir) if args.output_dir else OUTPUT_DIR

    # ── Device detection ─────────────────────────────────────────────────────
    if torch.backends.mps.is_available():
        device = "mps"
        print("Using Apple MPS GPU acceleration")
    elif torch.cuda.is_available():
        device = "cuda"
        print(f"Using CUDA GPU: {torch.cuda.get_device_name(0)}")
    else:
        device = "cpu"
        print("No GPU found - training on CPU (will be slow)")

    # ── Load model ───────────────────────────────────────────────────────────
    print(f"\nLoading base model: {BASE_MODEL}")
    processor = TrOCRProcessor.from_pretrained(BASE_MODEL)
    model     = VisionEncoderDecoderModel.from_pretrained(BASE_MODEL)

    # Required TrOCR decoder config
    model.config.decoder_start_token_id = processor.tokenizer.cls_token_id
    model.config.pad_token_id           = processor.tokenizer.pad_token_id
    model.config.eos_token_id           = processor.tokenizer.sep_token_id
    model.config.max_length             = 64
    model.config.early_stopping         = True
    model.config.no_repeat_ngram_size   = 3
    model.config.length_penalty         = 2.0
    model.config.num_beams              = 4

    # ── Load data ────────────────────────────────────────────────────────────
    col_filter = None if args.col == "all" else args.col
    pairs = _load_pairs(crops_dir, col_filter=col_filter)
    if not pairs:
        print(f"\nNo annotated crops found in {crops_dir}.")
        print("Run build_dataset.py first, then correct the .txt files.")
        sys.exit(1)

    print(f"Found {len(pairs)} labelled crops (column: {args.col})")

    # 85/15 train/eval split - shuffle first
    np.random.seed(42)
    indices = np.random.permutation(len(pairs)).tolist()
    pairs   = [pairs[i] for i in indices]

    split    = int(len(pairs) * 0.85)
    train_ds = ReceiptCellDataset(pairs[:split], processor, augment=not args.no_augment)
    eval_ds  = ReceiptCellDataset(pairs[split:], processor, augment=False)

    print(f"Train: {len(train_ds)}  |  Eval: {len(eval_ds)}")
    print(f"Epochs: {args.epochs}  |  Batch: {args.batch_size}  |  LR: {args.lr}")
    print(f"Data augmentation: {'off' if args.no_augment else 'on (rotation, brightness, blur)'}")

    # ── Training args ────────────────────────────────────────────────────────
    use_fp16 = (device == "cuda")

    training_args = Seq2SeqTrainingArguments(
        output_dir                  = str(output_dir),
        num_train_epochs            = args.epochs,
        per_device_train_batch_size = args.batch_size,
        per_device_eval_batch_size  = args.batch_size,
        learning_rate               = args.lr,
        warmup_ratio                = 0.1,
        weight_decay                = 0.01,
        predict_with_generate       = True,
        generation_max_length       = 64,
        logging_steps               = 20,
        eval_strategy               = "epoch",
        save_strategy               = "epoch",
        save_total_limit            = 3,
        load_best_model_at_end      = True,
        metric_for_best_model       = "cer",
        greater_is_better           = False,   # lower CER = better
        fp16                        = use_fp16,
        dataloader_num_workers      = 0,       # 0 is safer on Mac
        report_to                   = "none",
        lr_scheduler_type           = "cosine",
    )

    live_meta = {
        "base_model": BASE_MODEL, "train_samples": len(train_ds),
        "eval_samples": len(eval_ds), "epochs": args.epochs,
        "batch_size": args.batch_size, "lr": args.lr,
    }
    trainer = Seq2SeqTrainer(
        model            = model,
        args             = training_args,
        train_dataset    = train_ds,
        eval_dataset     = eval_ds,
        data_collator    = default_data_collator,
        compute_metrics  = make_compute_metrics(processor),
        callbacks        = [
            EarlyStoppingCallback(early_stopping_patience=3),
            LiveStatsCallback(output_dir, live_meta),
        ],
    )

    # ── Train ────────────────────────────────────────────────────────────────
    print(f"\nStarting training → checkpoints saved to {output_dir}")
    print("Watch CER (Character Error Rate) - lower is better. Target: < 0.10")
    train_result = trainer.train()

    # ── Save final model ─────────────────────────────────────────────────────
    final_dir = output_dir / "final"
    model.save_pretrained(final_dir)
    processor.save_pretrained(final_dir)

    # Save final training stats (marks training_complete: true)
    stats = {
        **live_meta,
        "final_loss":       round(train_result.training_loss, 4),
        "log_history":      trainer.state.log_history,
        "current_epoch":    args.epochs,
        "training_complete": True,
    }
    (output_dir / "training_stats.json").write_text(
        json.dumps(stats, indent=2), encoding="utf-8"
    )

    print(f"\n{'='*60}")
    print(f"Training complete!")
    print(f"  Final model:     {final_dir}")
    print(f"  Training stats:  {output_dir / 'training_stats.json'}")
    print()
    print("To use the fine-tuned model:")
    print(f"  export TROCR_HANDWRITTEN_MODEL={final_dir}")
    print()
    print("To evaluate before/after accuracy:")
    print("  python scripts/evaluate_pipeline.py")


if __name__ == "__main__":
    main()
