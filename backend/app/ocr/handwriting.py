from transformers import TrOCRProcessor, VisionEncoderDecoderModel
from PIL import Image
import io
from typing import Optional

_processor: Optional[TrOCRProcessor] = None
_model: Optional[VisionEncoderDecoderModel] = None

MODEL_NAME = "microsoft/trocr-base-handwritten"

def _load():
    global _processor, _model
    if _processor is None or _model is None:
        _processor = TrOCRProcessor.from_pretrained(MODEL_NAME)
        _model = VisionEncoderDecoderModel.from_pretrained(MODEL_NAME)

def handwriting_ocr(image_bytes: bytes) -> str:
    _load()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    pixel_values = _processor(images=img, return_tensors="pt").pixel_values
    generated_ids = _model.generate(pixel_values, max_new_tokens=64)
    text = _processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return text.strip()