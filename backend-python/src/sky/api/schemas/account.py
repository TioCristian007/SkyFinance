"""sky.api.schemas.account — Request/response schemas para /api/account/export-request."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DataExportRequestCreate(BaseModel):
    format: Literal["json", "csv"] = "json"


class DataExportRequestOut(BaseModel):
    id: str
    status: str
    format: str
    download_url: str | None
    expires_at: datetime | None
    requested_at: datetime
    delivered_at: datetime | None
