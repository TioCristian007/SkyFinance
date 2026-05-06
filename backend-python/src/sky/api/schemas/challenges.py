"""sky.api.schemas.challenges — Schemas Pydantic de desafíos."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ChallengeOut(BaseModel):
    id: str
    title: str
    description: str
    target_amount: int
    current_amount: int
    start_date: date
    end_date: date
    status: str  # "proposed" | "active" | "completed" | "declined"
    created_at: datetime


class ChallengeAcceptResponse(BaseModel):
    id: str
    status: str = "active"


class ChallengeDeclineResponse(BaseModel):
    id: str
    status: str = "declined"
