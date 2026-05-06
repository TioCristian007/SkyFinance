"""sky.api.schemas.summary — Schemas Pydantic de resumen financiero."""
from __future__ import annotations

from pydantic import BaseModel


class SummaryResponse(BaseModel):
    balance: int
    income: int
    expenses: int
    savings_rate: float
    net_flow: int
    period_days: int = 30


class CategoryBreakdown(BaseModel):
    category: str
    label: str
    amount: int
    percentage: float


class SummaryByCategoryResponse(BaseModel):
    categories: list[CategoryBreakdown]
    total_expenses: int
