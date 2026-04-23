"""Tests for the regex cleanup applied to header and footer OCR output."""

from app.ocr.key_fields_parser import parse_header, parse_footer


def test_parse_header_extracts_numeric_invoice_number():
    result = parse_header(
        header_text="INVOICE No: 12345",
        inv_no_text="12345",
        cust_name_raw="John Smith",
        cust_phone_raw="020 1234 5678",
        date_raw="12/03/2025",
    )
    assert result["invoice_number"] == "12345"


def test_parse_header_falls_back_to_header_text_anchor():
    result = parse_header(
        header_text="Invoice No: 98765",
        inv_no_text="",
        cust_name_raw="Acme Ltd",
        cust_phone_raw="",
        date_raw="01/01/2026",
    )
    assert result["invoice_number"] == "98765"


def test_parse_header_ignores_vat_digits():
    result = parse_header(
        header_text="VAT No: 987654321 Invoice No: 456",
        inv_no_text="",
        cust_name_raw="Test",
        cust_phone_raw="",
        date_raw="",
    )
    assert result["invoice_number"] == "456"


def test_parse_header_normalises_date_separators():
    result = parse_header(
        header_text="",
        inv_no_text="",
        cust_name_raw="",
        cust_phone_raw="",
        date_raw="12 03 2025",
    )
    assert result["invoice_date"] == "12/03/2025"


def test_parse_header_strips_invoice_to_label():
    result = parse_header(
        header_text="",
        inv_no_text="",
        cust_name_raw="INVOICE TO: Mr Smith",
        cust_phone_raw="",
        date_raw="",
    )
    assert result["customer"]["name"] == "Mr Smith"


def test_parse_footer_extracts_net_vat_due():
    text = "NET TOTAL 100.00 VAT 20.00 AMOUNT DUE 120.00"
    result = parse_footer(text)
    assert result["net_total"] == "100.00"
    assert result["vat"] == "20.00"
    assert result["amount_due"] == "120.00"


def test_parse_footer_handles_missing_fields():
    result = parse_footer("NET TOTAL 50.00")
    assert result["net_total"] == "50.00"
    assert result["vat"] == ""
    assert result["amount_due"] == ""


def test_parse_footer_strips_commas_from_thousands():
    text = "Net Total 1,234.56"
    result = parse_footer(text)
    assert result["net_total"] == "1234.56"
