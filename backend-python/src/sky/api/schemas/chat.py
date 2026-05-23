"""sky.api.schemas.chat — Schemas Pydantic de Mr. Money."""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    context_hint: str | None = None  # "challenges", "goals", etc. para routing local


class ChatTextResponse(BaseModel):
    type: str = "text"
    text: str


class ProposeChallenge(BaseModel):
    type: str = "propose_challenge"
    challenge_id: str          # id del catálogo MOCK_CHALLENGES (ej: "no_uber")
    reasoning: str             # por qué este desafío es relevante ahora


class NavigationResponse(BaseModel):
    type: str = "navigation"
    route: str
    label: str


ChatResponse = Annotated[
    ChatTextResponse | ProposeChallenge | NavigationResponse,
    Field(discriminator="type"),
]


class ChatUnifiedResponse(BaseModel):
    """Shape unificado para paridad con Node aiService.js → Sky.jsx lo consume directamente."""
    reply: str = ""
    proposals: list[dict[str, Any]] = []
    navigations: list[dict[str, Any]] = []
