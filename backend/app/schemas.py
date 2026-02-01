from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime


class SubmissionOut(BaseModel):
    id: str
    image_url: str
    extracted_data: Dict[str, Any]
    status: str
    created_at: datetime


class InvoiceItemIn(BaseModel):
    description: Optional[str]
    quantity: Optional[int]
    amount: Optional[float]
    confidence: Optional[float]


class ApproveSubmissionIn(BaseModel):
    items: List[InvoiceItemIn]