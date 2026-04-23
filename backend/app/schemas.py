"""Pydantic response models used by the FastAPI endpoints.

Each class defines the exact JSON shape returned for a given resource,
which keeps the API contract in one place and lets FastAPI generate
the OpenAPI schema automatically.
"""

from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime


class SubmissionOut(BaseModel):
    id: str
    image_url: str
    extracted_data: Dict[str, Any]
    status: str
    created_at: datetime


class InvoiceItemOut(BaseModel):
    id: str
    submission_id: Optional[str] = None
    invoice_id: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    confidence: Optional[float] = None


class InvoiceOut(BaseModel):
    id: str
    submission_id: str
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    net_total: Optional[float] = None
    vat: Optional[float] = None
    amount_due: Optional[float] = None
    created_at: datetime
    items: List[InvoiceItemOut] = []


class ProductOut(BaseModel):
    id: str
    name: str
    current_stock: int
