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
    # Acepta camelCase del frontend (title/targetAmount/deadline)
    # o snake_case interno (name/target_amount/target_date)
    name: str | None = Field(None, min_length=1, max_length=100)
    title: str | None = Field(None, min_length=1, max_length=100)
    target_amount: int | None = Field(None, gt=0)
    targetAmount: int | None = Field(None, gt=0)
    target_date: date | None = None
    deadline: date | None = None


class GoalPatchRequest(BaseModel):
    name: str | None = None
    target_amount: int | None = None
    target_date: date | None = None
    current_amount: int | None = None
