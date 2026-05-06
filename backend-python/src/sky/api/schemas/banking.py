"""sky.api.schemas.banking — Schemas Pydantic para endpoints bancarios."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SyncBankAccountResponse(BaseModel):
    started: bool = True
    job_id: str = Field(..., description="ARQ job_id para poll opcional")


class SyncAllResponse(BaseModel):
    started: bool = True
    job_id: str


class BankAccountOut(BaseModel):
    id: str
    bank_id: str
    bank_name: str
    bank_icon: str | None = None
    last_balance: int = 0
    last_sync_at: datetime | None = None
    last_sync_error: str | None = None
    status: str  # "active" | "syncing" | "error" | "waiting_2fa" | "disconnected"
    sync_count: int = 0
    minutes_ago: int | None = None
    account_type: str = "Cuenta"


class BankAccountListResponse(BaseModel):
    accounts: list[BankAccountOut]
    total_balance: int


class BankAccountConnectRequest(BaseModel):
    bank_id: str = Field(..., min_length=2, max_length=32)
    rut: str = Field(..., min_length=8, max_length=12)
    password: str = Field(..., min_length=4, max_length=128)
    bank_name: str | None = None


class BankAccountConnectedResponse(BaseModel):
    id: str
    bank_id: str
    status: str = "active"
    sync_job_id: str
