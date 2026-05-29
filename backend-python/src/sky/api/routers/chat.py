"""sky.api.routers.chat — POST /api/chat (Mr. Money) + GET /api/chat/history."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request

from sky.api.deps import require_user_id
from sky.api.middleware.rate_limit import limiter
from sky.api.schemas.chat import (
    ChatRequest,
    ChatTextResponse,
    ChatUnifiedResponse,
    NavigationResponse,
    ProposeChallenge,
)
from sky.core.config import settings
from sky.core.logging import get_logger

logger = get_logger("chat_router")

router = APIRouter(prefix="/api/chat", tags=["chat"])

_HISTORY_CAP = 50  # límite duro en GET /history


@router.post("", response_model=ChatUnifiedResponse)
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")  # type: ignore[untyped-decorator]
async def chat_endpoint(
    body: ChatRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(require_user_id),
) -> ChatUnifiedResponse:
    from sky.domain.mr_money import MrMoney

    response = await MrMoney().respond(
        user_id=user_id,
        message=body.message,
        history=body.history,
    )

    # Persistencia fire-and-forget (igual que _fire_aria)
    assistant_text = _extract_assistant_text(response)
    background_tasks.add_task(_persist_turns, user_id, body.message, assistant_text)
    background_tasks.add_task(_fire_aria, user_id, body.message, response)

    if isinstance(response, ChatTextResponse):
        return ChatUnifiedResponse(reply=response.text)
    if isinstance(response, ProposeChallenge):
        return ChatUnifiedResponse(
            reply=response.reasoning,
            proposals=[{
                "type": "propose_challenge",
                "input": {
                    "challenge_id": response.challenge_id,
                    "reasoning": response.reasoning,
                },
            }],
        )
    if isinstance(response, NavigationResponse):
        return ChatUnifiedResponse(
            reply=response.label,
            navigations=[{"simulation_type": response.route}],
        )
    return ChatUnifiedResponse(reply="")


@router.get("/history")
@limiter.limit(f"{settings.api_rate_limit_per_minute}/minute")  # type: ignore[untyped-decorator]
async def get_chat_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=_HISTORY_CAP),
    user_id: str = Depends(require_user_id),
) -> list[dict[str, Any]]:
    from sqlalchemy import text

    from sky.core.db import get_engine

    engine = get_engine()
    async with engine.connect() as conn:
        rs = await conn.execute(
            text("""
                SELECT role, content, created_at
                  FROM public.mr_money_messages
                 WHERE user_id = :uid
                 ORDER BY created_at ASC
                 LIMIT :lim
            """),
            {"uid": user_id, "lim": min(limit, _HISTORY_CAP)},
        )
        return [
            {
                "role": r["role"],
                "content": r["content"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rs.mappings().all()
        ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_assistant_text(
    response: ChatTextResponse | ProposeChallenge | NavigationResponse,
) -> str:
    if isinstance(response, ChatTextResponse):
        return str(response.text)
    if isinstance(response, ProposeChallenge):
        return str(response.reasoning)
    if isinstance(response, NavigationResponse):
        return str(response.label)
    return ""


async def _persist_turns(user_id: str, user_message: str, assistant_text: str) -> None:
    try:
        from sqlalchemy import text

        from sky.core.db import get_engine

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO public.mr_money_messages (user_id, role, content)
                    VALUES (:uid, 'user',      :user_msg),
                           (:uid, 'assistant', :asst_msg)
                """),
                {"uid": user_id, "user_msg": user_message, "asst_msg": assistant_text},
            )
    except Exception:
        logger.warning("mr_money_persist_failed", user_id=user_id, exc_info=True)


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
