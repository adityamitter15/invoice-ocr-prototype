"""Main OCR pipeline for AGW receipts. Combines Tesseract, TrOCR and EasyOCR."""

import io
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageOps
import pytesseract

from app.ocr.handwriting import (
    DEFAULT_MAX_TOKENS,
    _ensure_pil_rgb,
    _load_handwritten,
    _ocr_with,
    _pil_to_cv_bgr,
    normalize_document,
)
from app.ocr.region_detector import detect_regions, get_column_bounds
from app.ocr.key_fields_parser import parse_header, parse_footer


# Template constants tuned to the AGW invoice layout. All crop fractions are
# expressed relative to (image_width, header_end_y / footer_height).
@dataclass(frozen=True)
class TemplateConstants:
    trocr_target_h: int = 64
    max_table_rows: int = 28

    top_header_bottom_pct: float = 0.70
    inv_no_x_start: float = 0.72
    inv_no_x_end: float = 0.99
    inv_no_y_end_pct: float = 0.12

    name_x_start_pct: float = 0.14
    name_x_end_pct: float = 0.45
    name_y_start_pct: float = 0.58
    name_y_end_pct: float = 0.68

    date_x_start_pct: float = 0.55
    date_x_end_pct: float = 0.99
    date_y_start_pct: float = 0.80
    date_y_end_pct: float = 0.96

    desc_left_offset_px: int = 15
    desc_right_offset_px: int = 10

    footer_totals_top_pct: float = 0.05
    footer_totals_bottom_pct: float = 0.65
    footer_label_end_pct: float = 0.82


TEMPLATE = TemplateConstants()
TARGET_H = TEMPLATE.trocr_target_h
MAX_TABLE_ROWS = TEMPLATE.max_table_rows


_EASYOCR_READER = None

def _get_easyocr():
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        import easyocr
        _EASYOCR_READER = easyocr.Reader(['en'], gpu=False, verbose=False)
    return _EASYOCR_READER


# Column-rule fragments that bleed into TrOCR description reads as punctuation.
_LEADING_JUNK = r'^[Ili|,\s!\.\'"\/\(\)#\-]+'
_TRAILING_JUNK = r'[#|\'"\s\-]+$'


# Look-alike letter-to-digit corrections applied ONLY to numeric cells.
_DIGIT_SUBS = {
    'S': '5', 's': '5',
    'O': '0', 'o': '0', 'U': '0', 'Q': '0', 'D': '0',
    'l': '1', 'I': '1', 'i': '1',
    'Z': '2', 'z': '2',
    'G': '6',
    'B': '8', 'b': '8', 'k': '8',
    'A': '9', 'a': '0',
    'q': '9', 'g': '9',
}


# ─────────────────────────────────────────────────────────────────────────────
# Image helpers
# ─────────────────────────────────────────────────────────────────────────────

def _crop_cell(
    pil_img: Image.Image,
    x1: int, y1: int,
    x2: int, y2: int,
    pad: int = 3,
) -> Image.Image:
    """Crop a cell with a small outer pad to avoid clipping ink at the edge."""
    img_w, img_h = pil_img.size
    return pil_img.crop((
        max(0, x1 - pad),
        max(0, y1 - pad),
        min(img_w, x2 + pad),
        min(img_h, y2 + pad),
    ))


def remove_grid_lines(pil_img: Image.Image) -> Image.Image:
    """Erase the printed grid with morphological opening; returns grayscale PIL."""
    cv_img = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Invert so ink/lines are foreground for MORPH_OPEN.
    inv = cv2.bitwise_not(gray)

    kw = max(w // 6, 50)
    horiz_k = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 1))
    horiz_lines = cv2.morphologyEx(inv, cv2.MORPH_OPEN, horiz_k, iterations=2)
    horiz_lines = cv2.dilate(horiz_lines,
                             cv2.getStructuringElement(cv2.MORPH_RECT, (1, 3)))

    kh = max(h // 10, 30)
    vert_k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kh))
    vert_lines = cv2.morphologyEx(inv, cv2.MORPH_OPEN, vert_k, iterations=2)
    vert_lines = cv2.dilate(vert_lines,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1)))

    line_mask = cv2.add(horiz_lines, vert_lines)
    cleaned_inv = cv2.subtract(inv, line_mask)
    cleaned = cv2.bitwise_not(cleaned_inv)
    return Image.fromarray(cleaned)


def preprocess_cell_for_trocr(pil_img: Image.Image) -> Image.Image:
    """Binarise, denoise, pad and RGB-convert a cell crop for TrOCR."""
    cv_img = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=max(h // 2 | 1, 11),
        C=12,
    )

    noise_k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    clean = cv2.morphologyEx(binary, cv2.MORPH_OPEN, noise_k, iterations=1)
    clean = cv2.copyMakeBorder(clean, 8, 8, 16, 16, cv2.BORDER_CONSTANT, value=255)
    return Image.fromarray(clean).convert("RGB")


def _resize_for_trocr(pil_img: Image.Image) -> Image.Image:
    w, h = pil_img.size
    if h == 0:
        return pil_img
    scale = TARGET_H / h
    new_w = max(1, int(w * scale))
    return pil_img.resize((new_w, TARGET_H), Image.LANCZOS)


def _has_ink(pil_img: Image.Image, dark_thresh: int = 180, min_ratio: float = 0.005) -> bool:
    """Coarse dark-pixel ratio check; used for quantity/amount (too small for component analysis)."""
    gray = np.array(pil_img.convert("L"))
    if gray.size == 0:
        return False
    dark_pixels = np.count_nonzero(gray < dark_thresh)
    return (dark_pixels / gray.size) > min_ratio


def _has_ink_simple(pil_img: Image.Image, dark_thresh: int = 180, min_ratio: float = 0.005) -> bool:
    return _has_ink(pil_img, dark_thresh=dark_thresh, min_ratio=min_ratio)


def _has_written_content(
    pil_img: Image.Image,
    *,
    dark_thresh: int = 180,
    min_tall_components: int = 3,
    min_vertical_ratio: float = 0.22,
    min_area: int = 25,
) -> bool:
    """True when a description cell has real handwriting (not grid residue or descender leakage).

    Requires several tall components AND at least one below the top third - that
    eliminates descender-leakage false positives from the row above.
    """
    gray = np.array(pil_img.convert("L"))
    if gray.size == 0:
        return False
    row_h = gray.shape[0]
    binary = (gray < dark_thresh).astype(np.uint8)
    binary[:2, :] = 0
    binary[-2:, :] = 0
    eroded = cv2.erode(binary, np.ones((2, 2), np.uint8), iterations=1)
    num, _, stats, centroids = cv2.connectedComponentsWithStats(eroded, connectivity=8)
    tall         = 0
    below_top    = 0
    for k in range(1, num):
        ww, hh, area = stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT], stats[k, cv2.CC_STAT_AREA]
        if area < min_area:
            continue
        if hh >= row_h * min_vertical_ratio:
            tall += 1
            if centroids[k, 1] > row_h * 0.33:
                below_top += 1
    return tall >= min_tall_components and below_top >= 1


# ─────────────────────────────────────────────────────────────────────────────
# OCR helpers
# ─────────────────────────────────────────────────────────────────────────────

def _trocr_cell(pil_img: Image.Image, processor, model, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    preprocessed = preprocess_cell_for_trocr(pil_img)
    resized = _resize_for_trocr(preprocessed)
    return _ocr_with(processor, model, resized, max_new_tokens=max_tokens)


def _trocr_cell_with_confidence(pil_img: Image.Image, processor, model, max_tokens: int = DEFAULT_MAX_TOKENS):
    """Like `_trocr_cell` but also returns a 0-1 confidence from avg token log-prob."""
    import torch
    preprocessed = preprocess_cell_for_trocr(pil_img)
    resized = _resize_for_trocr(preprocessed)
    pil_rgb = _ensure_pil_rgb(resized)
    pixel_values = processor(images=pil_rgb, return_tensors="pt").pixel_values

    with torch.no_grad():
        outputs = model.generate(
            pixel_values,
            max_new_tokens=max_tokens,
            output_scores=True,
            return_dict_in_generate=True,
        )

    text = processor.batch_decode(outputs.sequences, skip_special_tokens=True)[0].strip()

    if outputs.scores:
        log_probs = []
        for i, score in enumerate(outputs.scores):
            probs = torch.softmax(score, dim=-1)
            # +1 because position 0 of sequences is the BOS token.
            token_id = outputs.sequences[0, i + 1]
            log_probs.append(torch.log(probs[0, token_id]).item())
        avg_log_prob = sum(log_probs) / len(log_probs) if log_probs else -10.0
        confidence = max(0.0, min(1.0, 1.0 + avg_log_prob / 5.0))
    else:
        confidence = 0.0

    return text, confidence


def _tesseract_region(pil_img: Image.Image, psm: int = 6) -> str:
    return pytesseract.image_to_string(
        pil_img, config=f"--psm {psm} --oem 3"
    ).strip()


def _easyocr_read(pil_img: Image.Image) -> str:
    reader = _get_easyocr()
    arr = np.array(pil_img.convert("RGB"))
    results = reader.readtext(arr, detail=0, paragraph=False)
    return " ".join(results).strip()


def _parse_amount_easyocr(raw: str) -> str:
    """Turn a raw EasyOCR read of an amount cell into a clean "pounds.pence" string."""
    if not raw:
        return ""
    normalised = raw.replace(",", " ").replace(".", " ")
    corrected = "".join(_DIGIT_SUBS.get(c, c) for c in normalised)
    groups = re.findall(r"\d+", corrected)
    if not groups:
        return ""

    # Anchor on the trailing 2-digit pence group; anything before the
    # immediately-preceding pounds group is treated as upstream column noise.
    if len(groups) >= 2 and len(groups[-1]) == 2:
        pounds = groups[-2].lstrip("0") or "0"
        return f"{pounds}.{groups[-1]}"

    # Fallback when no clean trailing 2-digit group: split last two digits as pence.
    all_digits = "".join(groups)
    if len(all_digits) >= 4:
        pounds = all_digits[:-2].lstrip("0") or "0"
        return f"{pounds}.{all_digits[-2:]}"
    if len(all_digits) == 3:
        return f"{all_digits[0]}.{all_digits[1:]}"
    return f"{all_digits}.00"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def process_receipt(image_bytes: bytes) -> Dict[str, Any]:
    """Run the AGW OCR pipeline on one image and return the structured fields."""
    pil_img = Image.open(io.BytesIO(image_bytes))
    pil_img = ImageOps.exif_transpose(pil_img).convert("RGB")
    pil_img = normalize_document(pil_img)

    cv_img = _pil_to_cv_bgr(pil_img)
    h, w = cv_img.shape[:2]

    regions = detect_regions(cv_img)
    col_bounds = get_column_bounds(w)

    header_end_y = regions["header_end_y"]
    table_end_y = regions["table_end_y"]
    row_ys = regions["row_ys"]

    processor, model = _load_handwritten()

    # Letterhead printed text (address, VAT, phone) - PSM 3 handles mixed layouts.
    top_header_img = pil_img.crop((0, 0, w, int(header_end_y * TEMPLATE.top_header_bottom_pct)))
    header_text = _tesseract_region(top_header_img, psm=3)

    # Invoice number is red on pink carbonless: Tesseract loses the red channel,
    # EasyOCR's CTC model keeps it.
    inv_no_img = pil_img.crop((
        int(w * TEMPLATE.inv_no_x_start), 0,
        int(w * TEMPLATE.inv_no_x_end), int(header_end_y * TEMPLATE.inv_no_y_end_pct),
    ))
    inv_no_text = _easyocr_read(inv_no_img)

    # Customer name crop excludes the "INVOICE TO:" label to the left; EasyOCR
    # first (stronger on short printed-style names), TrOCR as cursive fallback.
    name_img = pil_img.crop((
        int(w * TEMPLATE.name_x_start_pct),
        int(header_end_y * TEMPLATE.name_y_start_pct),
        int(w * TEMPLATE.name_x_end_pct),
        int(header_end_y * TEMPLATE.name_y_end_pct),
    ))
    cust_name = _easyocr_read(name_img)
    if not cust_name:
        cust_name = _trocr_cell(name_img, processor, model)

    # Phone line is almost always blank; skip the OCR call.
    cust_phone = ""
    customer_txt = f"{cust_name}\n{cust_phone}"

    # Invoice date: EasyOCR handles slash separators better than TrOCR here.
    date_img = pil_img.crop((
        int(w * TEMPLATE.date_x_start_pct),
        int(header_end_y * TEMPLATE.date_y_start_pct),
        int(w * TEMPLATE.date_x_end_pct),
        int(header_end_y * TEMPLATE.date_y_end_pct),
    ))
    if _has_written_content(date_img, min_tall_components=2):
        date_raw = _easyocr_read(date_img)
    else:
        date_raw = ""

    header_fields = parse_header(header_text, inv_no_text, cust_name, cust_phone, date_raw)

    # Strip the grid once on the full image - more reliable than per-cell.
    cleaned_pil = remove_grid_lines(pil_img)
    cleaned_rgb = cleaned_pil.convert("RGB")

    row_pairs: List[Tuple[int, int]] = [
        (row_ys[i], row_ys[i + 1]) for i in range(min(len(row_ys) - 1, MAX_TABLE_ROWS))
    ]
    if row_ys and len(row_pairs) < MAX_TABLE_ROWS:
        row_pairs.append((row_ys[min(len(row_ys) - 1, MAX_TABLE_ROWS)], table_end_y))

    line_items: List[Dict[str, Any]] = []
    for row_idx, (y_top, y_bot) in enumerate(row_pairs, start=1):
        if y_bot - y_top < 8:
            continue

        # Blank-row filter on connected components - dark-pixel ratio is fooled
        # by descender leakage and line-removal residue.
        desc_x1, desc_x2 = col_bounds["description"]
        desc_check_crop = _crop_cell(cleaned_rgb, desc_x1, y_top, desc_x2, y_bot)
        if not _has_written_content(desc_check_crop, min_tall_components=2):
            continue

        # Small left/right offsets skip the column rules that grid-removal
        # occasionally leaves behind (otherwise read as leading "I" or trailing "#").
        desc_img = _crop_cell(
            cleaned_rgb,
            desc_x1 + TEMPLATE.desc_left_offset_px,
            y_top,
            desc_x2 - TEMPLATE.desc_right_offset_px,
            y_bot,
        )
        desc_raw, desc_conf = _trocr_cell_with_confidence(desc_img, processor, model)
        desc_text = re.sub(_LEADING_JUNK, '', desc_raw)
        desc_text = re.sub(_TRAILING_JUNK, '', desc_text).strip()

        # Low confidence + short text usually means a hallucinated read on a blank cell.
        if desc_conf < 0.15 and len(desc_text) < 5:
            desc_text = ""

        # Vertical pad as a fraction of row height so it adapts to scan density.
        row_pad = max(4, int((y_bot - y_top) * 0.10))

        # EasyOCR handles isolated digits better than TrOCR; use the full
        # quantity column width (row-number column is separate) so 2-digit
        # values like "15" aren't split.
        qty_x1, qty_x2 = col_bounds["quantity"]
        qty_img = _crop_cell(
            cleaned_rgb, qty_x1,
            max(0, y_top - row_pad), qty_x2,
            min(h, y_bot + row_pad),
        )
        qty_text = ""
        if _has_ink_simple(qty_img):
            qty_up = qty_img.resize(
                (qty_img.width * 2, qty_img.height * 2), Image.LANCZOS,
            )
            qty_raw = _easyocr_read(qty_up)
            qty_corrected = "".join(_DIGIT_SUBS.get(c, c) for c in qty_raw)
            # Concatenate every digit run - 2-digit quantities are often split
            # into two boxes by EasyOCR.
            qty_text = "".join(re.findall(r"\d+", qty_corrected))

        # Read unit_price and amount columns together because larger pounds
        # values overflow the amount column; the parser anchors on the
        # trailing 2-digit pence group to discard any unit_price noise.
        up_x1, _ = col_bounds["unit_price"]
        _, am_x2 = col_bounds["amount"]
        amount_img = _crop_cell(
            cleaned_rgb, up_x1,
            max(0, y_top - row_pad), am_x2,
            min(h, y_bot + row_pad),
        )
        amount_text = ""
        if _has_ink_simple(amount_img):
            amount_up = amount_img.resize(
                (amount_img.width * 2, amount_img.height * 2), Image.LANCZOS,
            )
            amount_raw = _easyocr_read(amount_up)
            amount_text = _parse_amount_easyocr(amount_raw)

        # Writers often run the quantity into the description column.
        if not qty_text and desc_text:
            m = re.match(r"^([0-9]{1,3})[ ,]+(\S.*)$", desc_text)
            if not m:
                m = re.match(r"^([0-9])([A-Za-z].*)$", desc_text)
            if m:
                qty_text = m.group(1)
                desc_text = m.group(2)

        # Strip a leading quantity digit that bled into the description crop,
        # but only before an uppercase letter so product codes with long digit
        # runs (e.g. "500x 800 towel roll") survive.
        if desc_text:
            desc_text = re.sub(r"^\d{1,2}\s*[,/\-]?\s*(?=[A-Za-z])", "", desc_text)
            desc_text = re.sub(_LEADING_JUNK, '', desc_text).strip()

        if not any([qty_text, desc_text, amount_text]):
            continue

        line_items.append({
            "row":         row_idx,
            "quantity":    qty_text,
            "description": desc_text,
            "unit_price":  "",
            "amount":      amount_text,
            "confidence":  round(desc_conf, 2),
        })

    # Trim trailing signature/continuation rows past the last amount.
    if line_items:
        last_amount_idx = -1
        for i, item in enumerate(line_items):
            if item["amount"]:
                last_amount_idx = i
        if last_amount_idx >= 0:
            cutoff = last_amount_idx + 2
            line_items = line_items[:cutoff]

    # Footer: NET TOTAL / VAT / AMOUNT DUE stacked in ~1/3 height each.
    footer_img = pil_img.crop((0, table_end_y, w, h))
    footer_printed = _tesseract_region(footer_img, psm=6)

    fh = h - table_end_y
    totals_y1 = table_end_y + int(fh * TEMPLATE.footer_totals_top_pct)
    totals_y2 = table_end_y + int(fh * TEMPLATE.footer_totals_bottom_pct)
    totals_h = totals_y2 - totals_y1
    row_h = totals_h // 3

    fp_x1 = int(w * TEMPLATE.footer_label_end_pct)
    fp_x2 = col_bounds["amount"][1]

    def _footer_amount(row_idx: int) -> str:
        fy1 = totals_y1 + row_idx * row_h
        fy2 = fy1 + row_h
        if fy1 >= fy2 or fp_x1 >= fp_x2 or fy2 > h or fp_x2 > w:
            return ""
        crop = cleaned_rgb.crop((fp_x1, fy1, fp_x2, fy2))
        if crop.size[0] == 0 or crop.size[1] == 0:
            return ""
        if not _has_ink_simple(crop):
            return ""
        raw = _trocr_cell(crop, processor, model)
        groups = re.findall(r"\d+", raw)
        if not groups:
            return ""
        significant = [g for g in groups if len(g) >= 2]
        if not significant:
            return ""
        main = max(significant, key=len)
        # A leading "1" on 4+ digit reads is usually the box border.
        if len(main) >= 4 and main[0] == "1":
            main = main[1:]
        idx = groups.index(max(groups, key=len))
        pence_after = [g for g in groups[idx + 1:] if len(g) == 2]
        pence = pence_after[0] if pence_after else "00"
        return f"{main}.{pence}"

    # Start with whatever Tesseract found on the printed footer labels,
    # then overlay the direct TrOCR reads from the handwritten boxes.
    footer_fields = parse_footer(footer_printed)
    net_direct = _footer_amount(0)
    vat_direct = _footer_amount(1)
    due_direct = _footer_amount(2)
    if net_direct:
        footer_fields["net_total"] = net_direct
    if vat_direct:
        footer_fields["vat"] = vat_direct
    if due_direct:
        footer_fields["amount_due"] = due_direct

    item_lines = []
    for item in line_items:
        qty   = (item["quantity"]   or "").strip()
        desc  = (item["description"] or "").strip()
        price = (item["unit_price"] or "").strip()
        amt   = (item["amount"]     or "").strip()
        if qty or desc or amt:
            item_lines.append(f"  {qty:>4}  {desc:<55}  {price:>10}  {amt:>10}")

    items_block = "\n".join(item_lines) if item_lines else "  (no items detected)"

    raw_text = (
        f"[HEADER]\n{header_text}\n\n"
        f"[CUSTOMER]\n{customer_txt}\n\n"
        f"[LINE ITEMS]\n"
        f"   QTY  {'DESCRIPTION':<55}  {'UNIT PRICE':>10}  {'AMOUNT':>10}\n"
        f"{items_block}\n\n"
        f"[FOOTER]\n{footer_printed}"
    )

    return {
        **header_fields,
        "line_items":  line_items,
        **footer_fields,
        "raw_text":    raw_text,
    }


def process_receipt_to_text(image_bytes: bytes) -> str:
    """Return just the raw_text string (legacy handwriting API)."""
    return process_receipt(image_bytes).get("raw_text", "")
