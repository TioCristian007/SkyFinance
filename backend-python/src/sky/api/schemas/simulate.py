"""sky.api.schemas.simulate — Schemas Pydantic de proyecciones financieras."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectionRequest(BaseModel):
    target_amount: int = Field(..., gt=0)
    monthly_savings: int = Field(..., ge=0)
    current_savings: int = Field(0, ge=0)
    annual_return_pct: float = Field(0.0, ge=0.0, le=30.0)


class ProjectionPoint(BaseModel):
    month: int
    accumulated: int


class ProjectionResponse(BaseModel):
    months_to_goal: int | None
    final_amount: int
    points: list[ProjectionPoint]
    feasible: bool
    rationale: str
