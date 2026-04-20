"""Voucher data model (transient — WhatsApp is the source of truth)."""

from pydantic import BaseModel


class VoucherRecord(BaseModel):
    barcode_number: str
    amount: float
    purchased_at: str  # ISO-8601 with timezone
    order_id: int = 0
