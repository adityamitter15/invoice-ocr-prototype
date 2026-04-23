"""Tests for the amount-parsing helper in the OCR pipeline."""

from app.ocr.receipt_pipeline import _parse_amount_easyocr


def test_parse_amount_clean_two_groups():
    assert _parse_amount_easyocr("99 99") == "99.99"


def test_parse_amount_uses_trailing_pence_group():
    assert _parse_amount_easyocr("123 45 67") == "45.67"


def test_parse_amount_zero_pads_pence():
    assert _parse_amount_easyocr("150") == "1.50"


def test_parse_amount_empty_input_returns_empty():
    assert _parse_amount_easyocr("") == ""


def test_parse_amount_strips_stray_punctuation():
    assert _parse_amount_easyocr("12.34") == "12.34"


def test_parse_amount_corrects_digit_lookalikes():
    assert _parse_amount_easyocr("S0 00") == "50.00"
