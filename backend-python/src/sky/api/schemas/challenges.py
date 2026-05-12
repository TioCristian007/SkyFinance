"""sky.api.schemas.challenges — Schemas Pydantic de desafíos."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class ChallengeProgress(BaseModel):
    pct: int
    done: bool


class ChallengeItem(BaseModel):
    id: str
    label: str
    icon: str
    desc: str
    category: str | None
    limit_amt: int
    days: int
    pts: int
    difficulty: str
    progress: ChallengeProgress | None = None


class ChallengesResponse(BaseModel):
    active: list[ChallengeItem]
    completed: list[ChallengeItem]
    available: list[ChallengeItem]
    points: int


class ChallengeAcceptResponse(BaseModel):
    id: str
    status: str = "active"


class ChallengeDeclineResponse(BaseModel):
    id: str
    status: str = "declined"
