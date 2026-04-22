"""Regex cleanup of header and footer OCR output into structured fields."""

import re
from typing import Any, Dict


# Look-alike letter-to-digit map applied ONLY inside known numeric fields.
_DIGIT_LIKE = {
    "S": "5", "s": "5",
    "O": "0", "o": "0", "Q": "0", "D": "0",
    "I": "1", "l": "1", "i": "1", "|": "1",
    "Z": "2", "z": "2",
    "B": "8", "b": "8",
    "G": "6", "g": "9",
    "A": "4",
    "T": "7",
}


def _digitise(token: str) -> str:
    return "".join(_DIGIT_LIKE.get(c, c) for c in token)


def parse_header(
    header_text: str,
    inv_no_text: str,
    cust_name_raw: str,
    cust_phone_raw: str,
    date_raw: str,
) -> Dict[str, Any]:
    """Build the structured header dict from the raw OCR strings."""
    result: Dict[str, Any] = {
        "vendor": {},
        "invoice_number": "",
        "invoice_date": "",
        "customer": {"name": "", "phone": ""},
    }

    # Prefer the dedicated invoice-number crop (any 3-7 digit run is the
    # number); fall back to a "No:" anchor in the full header to avoid
    # picking up VAT or postcode digits.
    invoice_no = ""
    for candidate in re.findall(r"\d{3,7}", _digitise(inv_no_text)):
        if re.fullmatch(r"\d{3,7}", candidate):
            invoice_no = candidate
            break
    if not invoice_no:
        header_sanitised = re.sub(r"(?i)\bv\.?a\.?t\.?\s*no\.?\s*\S+", "", header_text)
        m = re.search(
            r"(?:invoice\s+)?no[:\s#.]+([A-Za-z0-9]{3,7})",
            header_sanitised, re.I,
        )
        if m:
            candidate = _digitise(m.group(1))
            if re.fullmatch(r"\d{3,7}", candidate):
                invoice_no = candidate
    result["invoice_number"] = invoice_no

    # Tolerate mixed separators in the handwritten date, normalise to "/".
    cleaned = re.sub(r"\s+", " ", date_raw.strip())
    m = re.search(r"(\d{1,2}[\-/\.\s]+\d{1,2}[\-/\.\s]+\d{2,4})", cleaned)
    if m:
        result["invoice_date"] = re.sub(r"[\-/\.\s]+", "/", m.group(1).strip()).strip("/")
    else:
        result["invoice_date"] = re.sub(r"[^0-9/\-\.]", "", date_raw).strip()

    # Strip the printed "INVOICE TO:" label if OCR caught it, drop leading
    # punctuation/digits, collapse OCR-inserted separators to spaces.
    name = re.sub(r"(?i)invoice\s*to[:\s]*", "", cust_name_raw).strip()
    name = re.sub(r"^[^A-Za-z]+", "", name).strip()
    name = re.sub(r"[:;.,/\\]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    result["customer"]["name"] = name

    result["customer"]["phone"] = re.sub(r"[^0-9\s\-]", "", cust_phone_raw).strip()

    return result


def parse_footer(footer_text: str) -> Dict[str, str]:
    """Extract NET TOTAL, VAT and AMOUNT DUE from the printed footer text."""
    result = {"net_total": "", "vat": "", "amount_due": ""}

    def _find(pattern: str) -> str:
        m = re.search(
            pattern + r"[:\s]*£?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
            footer_text, re.I,
        )
        return m.group(1).replace(",", "") if m else ""

    result["net_total"] = _find(r"net\s*total")
    result["vat"] = _find(r"v\.?a\.?t\.?")
    result["amount_due"] = _find(r"amount\s*due")
    return result
