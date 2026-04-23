"""TrOCR model loading, document normalisation and per-region OCR helpers."""

import os
from typing import Optional, Tuple

from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

import cv2
import numpy as np


_hw_processor: Optional[TrOCRProcessor] = None
_hw_model: Optional[VisionEncoderDecoderModel] = None

# Override with a fine-tuned checkpoint by setting TROCR_HANDWRITTEN_MODEL.
TROCR_HANDWRITTEN_MODEL = os.getenv("TROCR_HANDWRITTEN_MODEL", "microsoft/trocr-large-handwritten")

DEFAULT_MAX_TOKENS = int(os.getenv("TROCR_MAX_NEW_TOKENS", "96"))


def _load_handwritten() -> Tuple[TrOCRProcessor, VisionEncoderDecoderModel]:
    global _hw_processor, _hw_model
    if _hw_processor is None or _hw_model is None:
        _hw_processor = TrOCRProcessor.from_pretrained(TROCR_HANDWRITTEN_MODEL)
        _hw_model = VisionEncoderDecoderModel.from_pretrained(TROCR_HANDWRITTEN_MODEL)
    return _hw_processor, _hw_model


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


def _ocr_with(processor: TrOCRProcessor, model: VisionEncoderDecoderModel, img, max_new_tokens: int) -> str:
    pil_img = _ensure_pil_rgb(img)
    pixel_values = processor(images=pil_img, return_tensors="pt").pixel_values
    generated_ids = model.generate(pixel_values, max_new_tokens=max_new_tokens)
    text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return text.strip()
