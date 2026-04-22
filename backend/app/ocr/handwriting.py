"""TrOCR model loading, document normalisation and per-region OCR helpers."""

import io
import os
from pathlib import Path
from typing import Optional, Dict, Tuple

from PIL import Image, ImageOps
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

import cv2
import numpy as np


_hw_processor: Optional[TrOCRProcessor] = None
_hw_model: Optional[VisionEncoderDecoderModel] = None
_print_processor: Optional[TrOCRProcessor] = None
_print_model: Optional[VisionEncoderDecoderModel] = None

# Override with a fine-tuned checkpoint by setting TROCR_HANDWRITTEN_MODEL.
TROCR_HANDWRITTEN_MODEL = os.getenv("TROCR_HANDWRITTEN_MODEL", "microsoft/trocr-large-handwritten")
TROCR_PRINTED_MODEL = os.getenv("TROCR_PRINTED_MODEL", "microsoft/trocr-base-printed")

DEFAULT_MAX_TOKENS = int(os.getenv("TROCR_MAX_NEW_TOKENS", "96"))


def _load_handwritten() -> Tuple[TrOCRProcessor, VisionEncoderDecoderModel]:
    global _hw_processor, _hw_model
    if _hw_processor is None or _hw_model is None:
        _hw_processor = TrOCRProcessor.from_pretrained(TROCR_HANDWRITTEN_MODEL)
        _hw_model = VisionEncoderDecoderModel.from_pretrained(TROCR_HANDWRITTEN_MODEL)
    return _hw_processor, _hw_model


def _load_printed() -> Tuple[TrOCRProcessor, VisionEncoderDecoderModel]:
    global _print_processor, _print_model
    if _print_processor is None or _print_model is None:
        _print_processor = TrOCRProcessor.from_pretrained(TROCR_PRINTED_MODEL)
        _print_model = VisionEncoderDecoderModel.from_pretrained(TROCR_PRINTED_MODEL)
    return _print_processor, _print_model


# ----------------------------
# Image helpers
# ----------------------------

def _pil_to_cv_bgr(pil_img: Image.Image) -> np.ndarray:
    rgb = pil_img.convert("RGB")
    arr = np.array(rgb)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _ensure_pil_rgb(img) -> Image.Image:
    """Return a PIL RGB image from either a PIL input or a numpy array."""
    if isinstance(img, Image.Image):
        return img.convert("RGB")

    arr = np.array(img)
    if arr.ndim == 2:
        return Image.fromarray(arr).convert("RGB")
    if arr.ndim == 3:
        if arr.shape[2] == 1:
            return Image.fromarray(arr[:, :, 0]).convert("RGB")
        if arr.shape[2] == 4:
            return Image.fromarray(arr[:, :, :3]).convert("RGB")
        return Image.fromarray(arr).convert("RGB")

    raise ValueError(f"Unsupported image dimensions: {arr.ndim}")


def normalize_document(pil_img: Image.Image) -> Image.Image:
    """Rotate to portrait and deskew small angles via minAreaRect."""
    pil_img = pil_img.convert("RGB")
    w, h = pil_img.size

    if w > h:
        pil_img = pil_img.rotate(90, expand=True)

    cv_img = _pil_to_cv_bgr(pil_img)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    inv = 255 - thr
    coords = cv2.findNonZero(inv)
    if coords is None:
        return pil_img

    rect = cv2.minAreaRect(coords)
    angle = rect[-1]
    if angle < -45:
        angle = 90 + angle

    # Only correct small skews; larger angles are likely feature errors.
    if abs(angle) < 0.5 or abs(angle) > 12:
        return pil_img

    (h2, w2) = gray.shape[:2]
    M = cv2.getRotationMatrix2D((w2 // 2, h2 // 2), angle, 1.0)
    rotated = cv2.warpAffine(cv_img, M, (w2, h2), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    rgb = cv2.cvtColor(rotated, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb).convert("RGB")


def preprocess_for_handwriting(pil_img: Image.Image) -> Image.Image:
    """Adaptive threshold + morph-open; returns RGB because TrOCR rejects 2D input."""
    cv_img = _pil_to_cv_bgr(pil_img)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    gray = cv2.bilateralFilter(gray, 7, 50, 50)

    thr = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        12,
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    thr = cv2.morphologyEx(thr, cv2.MORPH_OPEN, kernel, iterations=1)

    return Image.fromarray(thr).convert("RGB")


def preprocess_for_printed(pil_img: Image.Image) -> Image.Image:
    cv_img = _pil_to_cv_bgr(pil_img)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    return Image.fromarray(gray).convert("RGB")


def crop_regions_v1(pil_img: Image.Image) -> Dict[str, Image.Image]:
    """Coarse 25/50/25 header/table/totals split used by the debug helper."""
    w, h = pil_img.size
    header = pil_img.crop((0, 0, w, int(h * 0.25)))
    table = pil_img.crop((0, int(h * 0.25), w, int(h * 0.75)))
    totals = pil_img.crop((0, int(h * 0.75), w, h))
    return {"header": header, "table": table, "totals": totals}


def _ocr_with(processor: TrOCRProcessor, model: VisionEncoderDecoderModel, img, max_new_tokens: int) -> str:
    pil_img = _ensure_pil_rgb(img)
    pixel_values = processor(images=pil_img, return_tensors="pt").pixel_values
    generated_ids = model.generate(pixel_values, max_new_tokens=max_new_tokens)
    text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return text.strip()


def ocr_handwritten(img, max_new_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    processor, model = _load_handwritten()
    return _ocr_with(processor, model, img, max_new_tokens=max_new_tokens)


def ocr_printed(img, max_new_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    processor, model = _load_printed()
    return _ocr_with(processor, model, img, max_new_tokens=max_new_tokens)


def handwriting_ocr(image_bytes: bytes) -> str:
    """Legacy entry point retained for API stability; returns raw_text."""
    from app.ocr.receipt_pipeline import process_receipt_to_text
    return process_receipt_to_text(image_bytes)


def handwriting_ocr_debug(image_bytes: bytes, save_dir: str = "debug_crops") -> Dict[str, str]:
    """Dump intermediate crops to disk and return per-region OCR text."""
    os.makedirs(save_dir, exist_ok=True)

    pil_img = Image.open(io.BytesIO(image_bytes))
    pil_img = ImageOps.exif_transpose(pil_img).convert("RGB")
    pil_img.save(os.path.join(save_dir, "00_upright.png"))
    norm = normalize_document(pil_img)
    norm.save(os.path.join(save_dir, "normalized.png"))

    regions = crop_regions_v1(norm)
    for key, region in regions.items():
        region.save(os.path.join(save_dir, f"{key}.png"))

    header_img = preprocess_for_printed(regions["header"])
    table_img = preprocess_for_handwriting(regions["table"])
    totals_img = preprocess_for_handwriting(regions["totals"])

    header_img.save(os.path.join(save_dir, "header_pre.png"))
    table_img.save(os.path.join(save_dir, "table_pre.png"))
    totals_img.save(os.path.join(save_dir, "totals_pre.png"))

    return {
        "header": ocr_printed(header_img, max_new_tokens=96),
        "table": ocr_handwritten(table_img, max_new_tokens=128),
        "totals": ocr_handwritten(totals_img, max_new_tokens=96),
    }


def dataset_paths() -> Dict[str, Path]:
    """Local dataset folders (not checked in)."""
    backend_root = Path(__file__).resolve().parents[2]
    data_root = backend_root / "data"
    return {
        "data_root": data_root,
        "raw": data_root / "receipts_raw",
        "normalized": data_root / "receipts_normalized",
        "crops": data_root / "crops",
        "labels": data_root / "labels",
    }