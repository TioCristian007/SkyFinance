"""sky.api.schemas.audit — Response schemas para /api/audit/me."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    event_type: str
    outcome: str
    resource_type: str | None
    resource_id: str | None
    detail: dict[str, Any] | None
    occurred_at: datetime


class AuditEventListResponse(BaseModel):
    events: list[AuditEventOut]
    total: int
    limit: int
    offset: int
