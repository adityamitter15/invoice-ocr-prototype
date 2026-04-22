#!/usr/bin/env python3
"""
label_helper.py - Terminal tool for correcting TrOCR predictions on crop images.

Opens each crop in Preview so you can see it, shows the TrOCR guess,
and lets you type the correct text (or press Enter to keep the guess).

Controls:
    Enter   - keep TrOCR guess as-is
    text    - type the correct transcription
    -       - mark as blank (skipped in training)
    u       - undo last label
    s       - skip for now
    q       - quit (progress is saved)

Progress is saved after every label so you can stop and resume anytime.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


def open_image(path: Path) -> None:
    try:
        subprocess.Popen(["open", str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def load_progress(progress_file: Path) -> set:
    if progress_file.exists():
        return set(json.loads(progress_file.read_text()))
    return set()


def save_progress(progress_file: Path, done: set) -> None:
    progress_file.write_text(json.dumps(sorted(done)))


def main():
    parser = argparse.ArgumentParser(description="Interactive crop labelling tool")
    parser.add_argument("--crops-dir", default=None)
    parser.add_argument("--col",       default="description",
                        help="Column to label: description | amount | all")
    parser.add_argument("--invoice",   default=None,
                        help="Label only a specific invoice (e.g. 000001)")
    args = parser.parse_args()

    crops_dir     = Path(args.crops_dir) if args.crops_dir else DATA_ROOT / "crops"
    progress_file = crops_dir / ".label_progress.json"
    done_set      = load_progress(progress_file)

    all_txt = sorted(crops_dir.rglob("*.txt"))
    if args.col != "all":
        all_txt = [t for t in all_txt if f"_{args.col}" in t.stem]
    if args.invoice:
        all_txt = [t for t in all_txt if t.parent.name == args.invoice]

    # Work from a flat list so we can go back with undo
    # Include already-done ones too so undo can reach them
    all_txt_with_png = [t for t in all_txt if t.with_suffix(".png").exists()]
    todo_indices     = [i for i, t in enumerate(all_txt_with_png)
                        if str(t) not in done_set]

    if not todo_indices:
        print("All crops are already labelled!")
        return

    total  = len(all_txt_with_png)
    n_done = len(done_set)

    print(f"\n{'='*60}")
    print(f"  AGW Receipt Labelling Tool  (column: {args.col})")
    print(f"  Progress: {n_done}/{total} done  |  {len(todo_indices)} remaining")
    print(f"{'='*60}")
    print("  Enter  = keep TrOCR guess")
    print("  text   = type correct transcription")
    print("  -      = mark as BLANK (empty row)")
    print("  u      = UNDO last label")
    print("  s      = skip for now")
    print("  q      = quit\n")

    # history: list of (txt_path, old_content) for undo
    history = []

    pos = 0  # index into todo_indices
    while pos < len(todo_indices):
        list_idx = todo_indices[pos]
        txt_path = all_txt_with_png[list_idx]
        img_path = txt_path.with_suffix(".png")

        current = txt_path.read_text(encoding="utf-8").strip()
        invoice = txt_path.parent.name
        crop    = txt_path.stem

        open_image(img_path)

        pct = int((n_done) / total * 100)
        print(f"[{n_done+1}/{total}  {pct}%]  {invoice}/{crop}")
        print(f"  TrOCR:  {current!r}")

        try:
            answer = input("  Correct: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nInterrupted - saving progress.")
            save_progress(progress_file, done_set)
            return

        if answer == "q":
            save_progress(progress_file, done_set)
            print("Saved. Bye!")
            return

        if answer == "u":
            if not history:
                print("  Nothing to undo.\n")
                continue
            # Restore previous label
            prev_path, prev_content = history.pop()
            prev_path.write_text(prev_content, encoding="utf-8")
            done_set.discard(str(prev_path))
            save_progress(progress_file, done_set)
            # Step back: find prev_path in all_txt_with_png and go back
            prev_idx = all_txt_with_png.index(prev_path)
            # Insert it before current pos in todo_indices
            todo_indices.insert(pos, prev_idx)
            if pos > 0:
                pos -= 1
            n_done -= 1
            print(f"  Undone - going back to {prev_path.parent.name}/{prev_path.stem}\n")
            continue

        if answer == "s":
            print("  Skipped.\n")
            pos += 1
            continue

        # Save the old content to history before overwriting
        history.append((txt_path, current))
        # Keep history limited to last 10
        if len(history) > 10:
            history.pop(0)

        if answer == "-":
            txt_path.write_text("", encoding="utf-8")
            print("  Marked as blank.\n")
        elif answer:
            txt_path.write_text(answer, encoding="utf-8")
            print(f"  Saved: {answer!r}\n")
        else:
            # Enter pressed - keep as-is, no write needed
            print(f"  Kept:  {current!r}\n")

        done_set.add(str(txt_path))
        save_progress(progress_file, done_set)
        n_done += 1
        pos += 1

    print(f"\nAll crops labelled! ({n_done} done)")
    print("Next:  python scripts/finetune_trocr.py")


if __name__ == "__main__":
    main()
