"""sky.api.schemas.chat — Schemas Pydantic de Mr. Money."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    context_hint: str | None = None  # "challenges", "goals", etc. para routing local


class ChatTextResponse(BaseModel):
    type: str = "text"
    text: str


class ProposeChallenge(BaseModel):
    type: str = "propose_challenge"
    title: str
    description: str
    target_amount: int
    duration_days: int
    rationale: str


class NavigationResponse(BaseModel):
    type: str = "navigation"
    route: str
    label: str


ChatResponse = Annotated[
    ChatTextResponse | ProposeChallenge | NavigationResponse,
    Field(discriminator="type"),
]
