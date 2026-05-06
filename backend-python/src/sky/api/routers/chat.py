"""sky.api.routers.chat — POST /api/chat (Mr. Money)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from sky.api.deps import require_user_id
from sky.api.schemas.chat import ChatRequest, ChatTextResponse, NavigationResponse, ProposeChallenge

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatTextResponse | ProposeChallenge | NavigationResponse)
async def chat_endpoint(
    body: ChatRequest,
    request: Request,
    user_id: str = Depends(require_user_id),
) -> ChatTextResponse | ProposeChallenge | NavigationResponse:
    from sky.domain.mr_money import MrMoney

    response = await MrMoney().respond(user_id=user_id, message=body.message)

    asyncio.ensure_future(_fire_aria(user_id, body.message, response))

    return response


async def _fire_aria(
    user_id: str,
    message: str,
    response: ChatTextResponse | ProposeChallenge | NavigationResponse,
) -> None:
    try:
        from sqlalchemy import text

        from sky.core.db import get_engine
        from sky.domain.aria import AnonProfile, track_behavioral_signal

        engine = get_engine()
        async with engine.connect() as conn:
            rs = await conn.execute(
                text(
                    "SELECT age_range, region, income_range, occupation"
                    " FROM public.profiles WHERE id = :uid"
                ),
                {"uid": user_id},
            )
            row = rs.mappings().first()

        profile = AnonProfile(
            age_range=str(row["age_range"]) if row and row["age_range"] else "unknown",
            region=str(row["region"]) if row and row["region"] else "unknown",
            income_range=str(row["income_range"]) if row and row["income_range"] else "unknown",
            occupation=str(row["occupation"]) if row and row["occupation"] else "unknown",
        )

        reply_text = response.text if isinstance(response, ChatTextResponse) else ""
        await track_behavioral_signal(profile, message, reply_text, user_id)
    except Exception:
        pass  # fire-and-forget, fail-safe
