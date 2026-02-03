import re
from typing import Dict, Any

def parse_key_fields(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    # Total (very simple prototype regex)
    m = re.search(r"(total|amount)\s*[:\-]?\s*£?\s*([0-9]+(?:\.[0-9]{2})?)", text, re.I)
    if m:
        out["total"] = m.group(2)

    # Date (common formats)
    m = re.search(r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", text)
    if m:
        out["date"] = m.group(1)

    # Invoice number
    m = re.search(r"(invoice\s*(no|number))\s*[:\-]?\s*([A-Za-z0-9\-]+)", text, re.I)
    if m:
        out["invoice_number"] = m.group(3)

    return out
