"""sky.api.schemas.goals — Schemas Pydantic de metas financieras."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class GoalOut(BaseModel):
    id: str
    name: str
    target_amount: int
    current_amount: int
    target_date: date | None
    progress_pct: float
    created_at: datetime


class GoalCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    target_amount: int = Field(..., gt=0)
    target_date: date | None = None


class GoalPatchRequest(BaseModel):
    name: str | None = None
    target_amount: int | None = None
    target_date: date | None = None
    current_amount: int | None = None
