"""sky.api.schemas.transactions — Schemas Pydantic de transacciones."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class TransactionOut(BaseModel):
    id: str
    amount: int
    category: str
    description: str
    raw_description: str
    date: date
    bank_account_id: str
    movement_source: str
    categorization_status: str


class TransactionListResponse(BaseModel):
    transactions: list[TransactionOut]
    total: int
    page: int
    page_size: int


class RecategorizeRequest(BaseModel):
    category: str


class TransactionPatchResponse(BaseModel):
    id: str
    category: str
    updated: bool = True
