"""sky.api.schemas.banking — Schemas Pydantic para endpoints bancarios."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SyncBankAccountResponse(BaseModel):
    started: bool = True
    job_id: str = Field(..., description="ARQ job_id para poll opcional")


class SyncAllResponse(BaseModel):
    started: bool = True
    job_id: str
